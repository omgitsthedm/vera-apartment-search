# AI-photo detection — what shipped, what didn't, and why

**Date:** 2026-08-03 · **Status:** deterministic tier shipped; ML tier deliberately deferred (needs David's call)

## The problem

AI-generated listing photos ("housefishing") are a live 2026 scam vector: a
generated interior sells a unit that doesn't exist, or dresses a unit far
worse than shown. VERA should say something true about this.

## Tier 1 — provenance (SHIPPED, `scripts/scan_photo_provenance.py`)

Reads what the file says about itself: C2PA/Content Credentials manifests,
XMP `trainedAlgorithmicMedia` source types, and EXIF `Software` tags naming
a generator (Stable Diffusion, Midjourney, DALL·E, Firefly, Flux, ComfyUI…).
When one is present, the image **declares itself synthetic** — a fact, not
an inference, which is the only kind of claim VERA prints as a verdict.

**Measured result on the 2026-08-03 pool (60 lead photos): zero signal.**
Every single image carried no camera EXIF and no generator marker, because
Craigslist, openigloo, and the rest re-encode uploads and strip all
metadata. Two consequences, both now enforced in code:

1. `no_camera_exif` is **useless as a suspicion signal** — it is true of
   100% of portal-hosted listing photos. It is recorded as context and is
   never surfaced. Surfacing it would flag every honest listing in the net.
2. The scanner still earns its keep at ~zero cost (60 images/night, cached
   by URL): the day a listing carries a real marker — likelier from the
   email-ingestion path, where images arrive closer to their source — VERA
   catches it with certainty instead of a guess.

## Tier 2 — a classifier (SHIPPED — this section was previously wrong)

Surveyed the public Hugging Face detectors on 2026-08-03:

| Model | Downloads | License | ONNX | Verdict |
|---|---|---|---|---|
| `Organika/sdxl-detector` | 123k | **cc-by-nc-3.0** | yes | **Unusable** — non-commercial licence, and VERA is a public product of an agency |
| `Ateeqq/ai-vs-human-image-detector` | 30k | apache-2.0 | no | Usable licence, but SigLIP needs a ~2.5GB torch stack |
| `haywoodsloan/ai-image-detector-deploy` | 19k | none stated | no | Unusable — no licence is not a permissive licence |

So the only ONNX-ready option is licence-blocked, and the only clean licence
needs torch on both the Mac *and* every GitHub Actions run.

**What actually shipped:** `scripts/detect_ai_photos.py` runs `umm-maybe/AI-image-detector` (**cc-by-4.0** — commercial use permitted *with attribution*, unlike the non-commercial `Organika/sdxl-detector` this file worried about). transformers + CPU torch are installed by the cloud job only, with the HF model cached between runs; the Mac skips it when transformers is absent. Output lands as `ai_photo_probability` / `ai_photo_suspect`, is **excluded from scoring**, and the ledger states it is probabilistic and not proof. The reasoning below was the argument *against*, kept because the false-positive concern it raises is real:

**The original caution:** The cost is ~2.5GB of dependencies and a heavy
cold start per cloud run; the benefit is a probability that — per the
honesty spine and David's own weighting decision — would be **excluded from
scoring** and shown only as a soft signal. Worse, the false-positive
profile is bad in exactly this domain: virtual staging is legal, disclosed,
and extremely common in rental listings, and detectors flag it readily.
Telling a renter a legitimately staged photo is "probably AI" is the kind of
confident wrongness VERA exists to avoid.

**If David wants it anyway** (say the word), the shape is: export
`Ateeqq/ai-vs-human-image-detector` to ONNX once, host the ~400MB artifact
outside git (Netlify large media or an HF model repo under his account),
and run inference with `onnxruntime` alone (~50MB) in both environments —
surfaced as "AI-photo likelihood: N%" with virtual-staging caveat text, and
still excluded from the score.


## Licence obligation (added 2026-08-04)

cc-by-4.0 requires attribution, and the repo carried none. The model is now
credited in README.md and on the app's System page. If the model is ever
swapped, the attribution must move with it — and any replacement must be
checked for a non-commercial clause, which would disqualify it here.
