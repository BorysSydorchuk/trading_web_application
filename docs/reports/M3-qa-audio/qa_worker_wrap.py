"""QA harness: run the app worker unchanged, but record raw vs normalized transcript per
glossary call into $QA_GLOSSARY_LOG (scratch, never the repo). Product code is not modified."""
import json
import os
import sys

from app.domain.transcript_glossary import TranscriptGlossary

_orig_apply = TranscriptGlossary.apply


def _apply(self, text):
    out, count = _orig_apply(self, text)
    with open(os.environ["QA_GLOSSARY_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"raw": text, "normalized": out, "count": count}, ensure_ascii=False) + "\n")
    return out, count


TranscriptGlossary.apply = _apply

from app.worker.main import main  # noqa: E402

sys.exit(main())
