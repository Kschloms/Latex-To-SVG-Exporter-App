# LaTeX Snippets

A small PyQt6 desktop app for composing LaTeX math expressions, previewing them inline, and copying the result as SVG or PNG — designed for pasting into Affinity Designer (or any other vector/document tool) with full Computer Modern fidelity.

![workflow: type → compile → copy SVG → paste into Affinity]

---

## Motivation

LaTeX-rendered math (via `latex` + `dvisvgm`) looks noticeably better in figures than native Unicode fonts like STIX Two — especially for bra-ket notation, `\otimes`, and Greek letters. This tool makes the compile-preview-copy loop fast enough to use routinely while building thesis figures.

---

## Requirements

### Python

- **Python 3.10+**
- **PyQt6** — UI framework

```bash
pip install PyQt6
```

### System tools

All three must be on your `PATH`. The app will warn on launch if any are missing.

| Tool | Purpose | Install |
|---|---|---|
| `latex` | Compile `.tex` → `.dvi` | TeX Live (see below) |
| `dvisvgm` | Convert `.dvi` → `.svg` | Bundled with TeX Live |
| `pdf2svg` | Convert `.pdf` → `.svg` (pdflatex mode only) | Separate install (see below) |

#### TeX Live

**Linux (Debian/Ubuntu):**
```bash
sudo apt install texlive-latex-extra texlive-science dvisvgm
```

**Linux (minimal, manual):**
```bash
sudo apt install texlive-base texlive-latex-recommended texlive-science dvisvgm
```

**macOS:**
```bash
brew install --cask mactex        # full install (~5 GB), includes dvisvgm
# or for a lighter install:
brew install basictex             # then: sudo tlmgr install physics standalone dvisvgm
```

**Windows:**
Install [MiKTeX](https://miktex.org/) or [TeX Live for Windows](https://tug.org/texlive/windows.html). Make sure the bin directory is added to `PATH`. `dvisvgm` is included in both.

#### pdf2svg (only needed if using the `pdflatex` compiler option)

```bash
# Linux
sudo apt install pdf2svg

# macOS
brew install pdf2svg
```

### LaTeX packages

The following packages must be available in your TeX distribution. They are all included in `texlive-science` / `texlive-latex-extra`:

| Package | Used for |
|---|---|
| `standalone` | Tight-bounding-box document class for snippets |
| `preview` | Standalone document class option |
| `amsmath` | Core math environments |
| `amssymb` | Extended math symbols |
| `physics` | `\ket{}`, `\bra{}`, `\braket{}`, etc. |
| `braket` | Alternative bra-ket notation (optional, off by default) |

If a package is missing, `latex` will error and the message will appear in the error panel. Install missing packages with:

```bash
# TeX Live
sudo tlmgr install <package-name>

# MiKTeX — installs automatically on first use
```

---

## Installation

No installation needed beyond the dependencies above. Just run:

```bash
python latex_snippets.py
```

To make it launchable from anywhere, you can add a shell alias:

```bash
# ~/.bashrc or ~/.zshrc
alias latexsnip='python /path/to/latex_snippets.py'
```

Or on Linux, create a `.desktop` file for your application launcher.

---

## Usage

### Basic workflow

1. Type a LaTeX math expression in the input panel (no `$` delimiters needed — the app wraps it automatically)
2. Press **Ctrl+Enter** to compile
3. Preview appears on the right
4. Press **Copy SVG** and paste into Affinity Designer, Inkscape, etc.
   — or **Copy PNG** for raster output at your configured DPI

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Enter` | Compile |
| `Ctrl+S` | Save snippet to history |
| `Ctrl+Shift+C` | Copy SVG to clipboard |

### Quick inserts

Buttons along the bottom of the input panel insert common physics notation at the cursor position: `\ket{}`, `\bra{}`, `\braket{}`, `\otimes`, `\Omega_{\beta}`, `\hat{H}`, `\frac{}{}`, `\dagger`, `\sigma_z`, `\mathrm{}`.

### History

Every successful compile is auto-saved to history (configurable in Settings). The **History** tab lists all saved snippets. Double-click any entry to load and recompile it. Right-click for rename/delete options.

Snippets are stored in `~/.latex_snippets/snippets.json` — plain JSON, easy to back up or edit manually.

---

## Settings

Open via the **⚙ Settings** button in the toolbar.

| Setting | Default | Notes |
|---|---|---|
| Compiler | `latex` | `latex` (→ dvisvgm) is recommended. Use `pdflatex` only if you need PDF-specific packages; requires `pdf2svg`. |
| Font size | 11 pt | Maps to the nearest standard LaTeX class size option. |
| Math mode | `display` | `display` uses `\[ \]` (centred, full size). `inline` uses `$ $` (text-height). |
| PNG DPI | 300 | Resolution for Copy PNG and Export PNG. Use 300 for print, 150 for screen. |
| SVG border | 2 pt | Padding around the expression in the output SVG, in addition to the `standalone` class border. |
| Auto-save | On | Saves every compiled expression to history automatically. |
| Packages | see above | Toggle individual packages on/off. Changes take effect on next compile. |
| Custom preamble | (empty) | Free-form LaTeX lines injected after the package declarations, e.g. `\newcommand{\dd}[1]{\mathrm{d}#1}`. |

Settings are persisted to `~/.latex_snippets/settings.json`.

---

## Output files

| Path | Contents |
|---|---|
| `~/.latex_snippets/snippets.json` | Saved snippet history |
| `~/.latex_snippets/settings.json` | App settings |
| `~/.latex_snippets/` (tmp subdirs) | Temporary compile artifacts — cleaned up automatically |

---

## Troubleshooting

**"Tool not found: latex — is TeX Live installed?"**
`latex` is not on your `PATH`. Check your TeX Live installation and that the bin directory is exported:
```bash
which latex        # should return a path
echo $PATH         # check TeX Live bin is in there
```

**"invalid bounding box format"**
You are using a very old version of `dvisvgm` (pre-2.x). Update via your package manager or `tlmgr update dvisvgm`.

**"Compile timed out"**
The compile took more than 30 seconds — usually caused by a runaway macro or an infinite loop in the expression. Check your LaTeX for unmatched braces.

**Preview looks blurry**
The preview renders at your OS display scale. Use the scale slider to zoom in. The SVG and PNG outputs are always full resolution regardless of preview scale.

**`\ket{}` not recognised**
The `physics` package must be enabled in Settings → Packages. Make sure `texlive-science` is installed (it includes `physics.sty`).

---

## Affinity Designer workflow tips

- **Paste SVG as vector:** In Affinity Designer, use *Edit → Paste* after Copy SVG. The expression lands as a fully editable group of vector paths.
- **Colour:** Ungroup the pasted SVG and select all paths, then change the fill colour in the Fill panel.
- **Sizing:** Scale by dragging a corner handle. Hold Shift to constrain proportions. The SVG is resolution-independent so scaling up never loses quality.
- **Alignment:** Use Affinity's alignment tools to align the placed expression to other objects. The bounding box is tight to the expression thanks to the `standalone` class.

---

## License

MIT — do whatever you like with it.