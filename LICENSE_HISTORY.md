# 라이선스 이력 (License History)

Copyright © 2026 Beomjoon Kim (bj0322) — https://github.com/pidstech/POSCHAT

## 요약

| 기간 | 라이선스 | 근거 |
|---|---|---|
| 커밋 `b0bacc5`(2026-10-18, "Prepare public distribution documentation and MIT licensing") ~ 커밋 `137ced8` | MIT | 그 시점의 `LICENSE` |
| 커밋 `3edf859`(2026-10-23, "chore(license): license new versions under AGPL-3.0-only")부터 | **AGPL-3.0-only** | 현재 `LICENSE`(GNU AGPL v3 공식 원문) |

`b0bacc5` 이전 커밋에는 `LICENSE` 파일이 없었습니다. 저장소는 v1.1.0 소스 스냅샷에서 시작했습니다(README 참고).

## MIT로 배포된 버전

GitHub의 다음 태그(와 그 Release 파일)는 MIT License로 배포되었습니다: v1.2.0, v1.3.0, v1.3.1, v1.4.0, v1.5.0, v1.6.0, v1.7.0, v1.7.1, v1.8.0, v1.8.2, v1.9.0, v1.9.1, v1.9.2.

- 이 버전들을 받은 사람이 MIT 조건으로 가진 권리는 **그대로 유지**됩니다. 이 전환은 과거 배포본의 권리를 철회하지 않습니다.
- MIT 원문은 Git 이력에 보존되어 있습니다: `git show b0bacc5:LICENSE` 또는 위 태그의 `LICENSE`.
- 전환 커밋 직전(`137ced8`)까지의 코드도 그 시점의 MIT 조건으로 쓸 수 있습니다.

## AGPL-3.0-only 적용 범위

- **적용 시작**: 커밋 `3edf859`(2026-10-23). 이 커밋이 포함된 첫 공식 배포본은 **v1.10.0**(이 문서를 쓰는 시점에 아직 태그·배포 전)입니다.
- 이후 이 저장소의 프로젝트 자체 코드·문서와 그 공식 배포본(Windows 설치 파일, macOS DMG, Android APK, GitHub Releases)에 AGPL-3.0-only를 적용합니다.
- "or later"는 적용하지 않습니다(SPDX: `AGPL-3.0-only`).
- 원문 외의 추가 조건·금지 조항(예: 상업적 이용 금지)은 두지 않습니다.

## 기존 MIT 코드와 새 AGPL 코드의 구분

- 전환 커밋 이전부터 있던 코드는 그 이전 버전에서 MIT로 받을 수 있습니다. 전환 이후 배포본은 그 코드를 포함한 전체 저작물을 AGPL-3.0-only로 배포합니다(MIT는 이런 재배포를 허용합니다).
- 전환 이후 추가·수정된 코드는 AGPL-3.0-only로만 제공됩니다. 어느 줄이 언제 들어왔는지는 `git log`·`git blame`으로 확인할 수 있습니다.
- 각 소스 파일 머리의 `SPDX-License-Identifier: AGPL-3.0-only`는 현재 판의 라이선스를 나타냅니다.

## 다른 기여자

MIT 시기에 다른 기여자의 커밋이 있습니다(`b807f38`, `b5451df`, PR #8). 그 기여는 MIT로 제공되었고 MIT는 재라이선스 배포를 허용하지만, 그 부분의 저작권 표시는 해당 기여자에게 남습니다.

## 제3자 구성 요소

`web/vendor/`, `licenses/`, Gradle wrapper 등 제3자 파일은 이 전환과 관계없이 각자의 라이선스를 따릅니다. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 참고.
