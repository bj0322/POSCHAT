# Third-party notices

The project MIT license covers original project material. The following
bundled third-party files retain their upstream notices and licenses.

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

HWP reading follows the publicly released Hancom HWP 5.0 file format
specification; this project is not affiliated with Hancom.

The built-in `paper`, `notion` and `hyperframes` MCP servers bundle no
third-party code. At run time they call public services under those
services' own terms: the arXiv API, the Semantic Scholar API (Allen Institute
for AI) and the Notion API. The `hyperframes` server downloads and runs the
HyperFrames CLI (https://github.com/heygen-com/hyperframes, Apache-2.0) with
`npx` on the user's PC; it is not included in the installer. The starter
composition and authoring guide in `hyperframes_mcp.py` follow the composition
format described in the HyperFrames documentation. This project is not
affiliated with arXiv, the Allen Institute for AI, Notion or HeyGen.

POSTECH names and marks belong to their respective owners. This project
license grants no trademark rights or access rights to the POSTECH GenAI API.
