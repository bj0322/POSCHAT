# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""음성 인식 테스트에 쓰는 모델과 시험 음성을 내려받는다(CI의 tests 작업이 부른다).

    python tests/fetch_test_models.py <폴더>

<폴더>/stt_models/에 앱과 같은 구조로 VAD와 한국어 모델을, <폴더>/test_wavs/에 모델 저장소의 시험 음성 4개와
정답(trans.txt)을 둔다. 모두 커밋을 고정하고 SHA-256으로 확인한다(목록은 안드로이드 앱의 po_bench와 같이 쓴다).
테스트는 POSCHAT_TEST_MODELS=<폴더>로 찾는다.
"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "android" / "app" / "src" / "main" / "python")]
import po_bench  # noqa: E402
import stt  # noqa: E402


def main(target):
    target = Path(target)
    with patch.object(stt, "MODELS_DIR", target / "stt_models"):
        po_bench.fetch(target / "test_wavs")
    print(f"준비 완료: {target}")


if __name__ == "__main__":
    main(sys.argv[1])
