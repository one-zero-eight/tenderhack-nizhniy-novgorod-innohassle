"""Download the pinned RuBERT model at build/setup time, never during a request."""

import argparse

from huggingface_hub import snapshot_download

MODEL_ID = "cointegrated/rubert-tiny-toxicity"
MODEL_REVISION = "5d37eff844868e243467e4c38898bad46c271af2"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="models/rubert-tiny-toxicity")
    args = parser.parse_args()
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=args.output,
        allow_patterns=["*.json", "vocab.txt", "model.safetensors", "README.md"],
    )


if __name__ == "__main__":
    main()
