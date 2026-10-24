# Third-party notices

The project license (AGPL-3.0-only from commit 3edf859 and v1.10.0; MIT for
v1.9.2 and earlier, see LICENSE_HISTORY.md) covers original project
material only. The following bundled third-party files retain their
upstream notices and licenses.

| Bundled file | Version | Upstream | License text |
|---|---|---|---|
| `web/vendor/marked.min.js` | 12.0.2 | https://github.com/markedjs/marked/tree/v12.0.2 | [Marked and Markdown notices](licenses/marked-LICENSE.md) |
| `web/vendor/purify.min.js` | DOMPurify 3.1.6 | https://github.com/cure53/DOMPurify/tree/3.1.6 | [Apache-2.0 OR MPL-2.0](licenses/DOMPurify-LICENSE.txt) |
| `web/vendor/katex/` (`katex.min.js`, `katex.min.css`, `fonts/*.woff2`) | KaTeX 0.16.22 | https://github.com/KaTeX/KaTeX/tree/v0.16.22 | [MIT](licenses/KaTeX-LICENSE.txt) |

Marked and DOMPurify are bundled unchanged from the imported v1.1.0 source.
KaTeX files are copied unchanged from the `katex@0.16.22` npm package
(`dist/`); only the WOFF2 fonts are included, which the stylesheet lists first. Original
copyright and license headers remain intact. Marked's upstream license file
also includes the Markdown redistribution notice. DOMPurify's upstream
license file includes both offered license texts.

Plugins installed from the Plugins screen (1.12) are downloaded at the
user's request from https://github.com/anthropics/knowledge-work-plugins
(Apache-2.0) and are not bundled with the app. Each installed plugin keeps
its own LICENSE file in the user's data folder (`plugins/<name>/`).

Python packages listed in `requirements.txt` and build dependencies are
installed separately and retain their respective licenses. When distributing
a built installer, include the applicable dependency license notices with it.
The installer bundles these runtime packages (and their dependencies) for
document reading and the built-in Office MCP servers:

| Package | Purpose | License |
|---|---|---|
| pypdf | PDF text extraction | BSD-3-Clause |
| olefile | HWP 5.0 container reading | BSD-2-Clause |
| openpyxl | Excel reading and writing | MIT |
| python-docx | Word writing | MIT |
| python-pptx | PowerPoint writing | MIT |
| lxml (via python-docx, python-pptx) | XML processing | BSD-3-Clause |
| Pillow (via python-pptx) | Image handling | MIT-CMU (HPND) |
| XlsxWriter (via python-pptx) | Chart data | BSD-2-Clause |
| et-xmlfile (via openpyxl) | XML writing | MIT |
| typing_extensions | Typing backports | PSF-2.0 |
| numpy | Audio buffers for PO노트 | BSD-3-Clause |
| sounddevice | Microphone capture for PO노트 | MIT |
| PortAudio (via sounddevice) | Audio I/O library | MIT-style (PortAudio license) |
| sherpa-onnx (and its bundled ONNX Runtime) | On-device speech recognition and voice activity detection | Apache-2.0 (ONNX Runtime: MIT) |
| requests, urllib3, charset-normalizer, idna | HTTP | Apache-2.0, MIT, MIT, BSD-3-Clause |
| certifi | CA certificates | MPL-2.0 |
| anthropic | Personal Claude API (official Anthropic Python SDK) | Apache-2.0 |
| httpx2, httpcore2, h11, anyio, sniffio, jiter, docstring-parser (via anthropic) | SDK HTTP client and helpers | BSD-3-Clause, BSD-3-Clause, MIT, MIT, MIT OR Apache-2.0, MIT, MIT |
| pydantic, pydantic-core, annotated-types, typing-inspection (via anthropic) | SDK data types | MIT |
| opentelemetry-api (via anthropic) | SDK tracing hooks (not configured by the app) | Apache-2.0 |
| truststore | OS certificate store | MIT |
| cryptography, cffi, pycparser | Sync encryption (AES-256-GCM) | Apache-2.0 OR BSD-3-Clause, MIT-0, BSD-3-Clause |
| keyring, jaraco.classes/context/functools, more-itertools | Connector tokens in the OS credential store | MIT |
| pywebview, bottle, proxy_tools | Desktop window | BSD-3-Clause, MIT, MIT |
| pythonnet, clr_loader (Windows) / pyobjc (macOS) | pywebview platform backends | MIT |
| CPython | The bundled Python interpreter | PSF-2.0 |
| PyInstaller bootloader | Starts the bundled app | GPL-2.0-or-later with the PyInstaller bootloader exception |

The desktop builds copy the license and notice files that each bundled
Python package ships into `licenses/python/<package>-<version>/` inside the
app. The app shows all of them under Settings → Third-party licenses.

The Android app bundles the Chaquopy runtime (MIT) with CPython 3.11
(PSF-2.0), the Android builds of the Python packages above from the Chaquopy
package repository (including numpy, BSD-3-Clause, and cryptography 42.0.8),
AndroidX core/activity/webkit and the Kotlin standard library (Apache-2.0),
and the
`libsherpa-onnx-c-api.so` and `libonnxruntime.so` libraries taken unchanged
from the official sherpa-onnx 1.13.8 Android package
(https://github.com/k2-fsa/sherpa-onnx/releases/tag/v1.13.8; sherpa-onnx:
Apache-2.0, ONNX Runtime: MIT).

HWP reading follows the publicly released Hancom HWP 5.0 file format
specification; this project is not affiliated with Hancom.

The built-in `paper`, `notion` and `firecrawl` MCP servers bundle no
third-party code. At run time they call public services under those
services' own terms: the arXiv API, the Semantic Scholar API (Allen
Institute for AI), the Notion API and the Firecrawl API. The recommended
`playwright` server downloads and runs Microsoft Playwright MCP
(https://github.com/microsoft/playwright-mcp, Apache-2.0) with `npx` on the
user's PC only when the user turns it on; it is not included in the
installer. This project is not affiliated with arXiv, the Allen Institute
for AI, Notion, Firecrawl or Microsoft.

PO노트 speech models are not included in the installer. The app downloads
them from Hugging Face, pinned by commit and checked by SHA-256: the small
voice-activity model on the first recording, and a recognition model only
when the user downloads it for local speech recognition. They remain under
their publishers' terms: the Silero VAD model
(https://huggingface.co/csukuangfj/vad), the k2-fsa Korean Zipformer model
(https://huggingface.co/k2-fsa/sherpa-onnx-zipformer-korean-2024-06-24) and
the SenseVoice Small model converted for sherpa-onnx
(https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17).
Silero VAD is MIT-licensed and the Korean Zipformer model is Apache-2.0 (converted
from johnBamma/icefall-asr-ksponspeech-zipformer-2024-06-24). SenseVoice Small is
distributed by Alibaba under the FunASR Model Open Source License Agreement 1.1
(https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE), which requires keeping
the source, author and model name; it is not a free-software license and the model is
never bundled with POSCHAT.

Version 1.10 connectors call the GitHub, Google Workspace, Zotero, Semantic
Scholar, arXiv and (when the user configures them) Qdrant, embedding and
Langfuse services at run time under those services' own terms. No code from
those services is bundled.

POSTECH names and marks belong to their respective owners. This project
license grants no trademark rights or access rights to the POSTECH GenAI API.
