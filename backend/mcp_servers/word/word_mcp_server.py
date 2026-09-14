"""Serveur MCP Word — documents .docx via python-docx.

Dialog avec le client sur stdio (MCP). Les noms de fichiers arrivent déjà
namespacés par tenant (<tenant>/<fichier>, voir McpBridgeService) et sont
résolus relativement au répertoire de travail du processus (cwd =
data/mcp_documents/word). Défense en profondeur : la traversée de répertoire
reste refusée ici même si le client oublie de valider.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Cm, Pt

from mcp.server.mcpserver import MCPServer

DOCX_SUFFIX = ".docx"
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._\-\u00A0-\uFFFF]+$")


def _cwd() -> Path:
    return Path.cwd()


def _unsafe_reason(value: str) -> str | None:
    """Valide un nom de fichier venant du bridge (namespacé par tenant).

    Formats acceptés :
        - `fichier.docx`                → racine du cwd (liste de fichiers)
        - `<tenant_id>/fichier.docx`    → sous-dossier tenant (le bridge isole)
    Tout le reste (absolu, URL, `..`, plus d'un niveau, segment vide ou
    « . ») est une tentative d'évasion du dossier de travail.
    """
    if not value or value.startswith(("/", "\\")):
        return "chemin absolu"
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        return "schéma URL"
    if ".." in value.replace("\\", "/").split("/"):
        return "segment `..` interdit"
    parts = value.replace("\\", "/").split("/")
    if len(parts) > 2:
        return "plus d'un sous-dossier"
    if any(not part or part in (".",) or not SAFE_NAME_RE.fullmatch(part) for part in parts):
        return "caractères invalides"
    return None


def _check(value: str) -> None:
    reason = _unsafe_reason(value)
    if reason:
        raise ValueError(f"Nom de fichier invalide ({reason}) : « {value} »")


def _target(filename: str) -> Path:
    """Réalise le chemin cible sous cwd, en ajoutant .docx si nécessaire.

    L'ajout d'extension est déterministe : si `foo` existe déjà en tant que
    `foo.docx`, on le retrouve ; sinon on cible `foo.docx`.
    """
    _check(filename)
    base = _cwd() / filename.replace("\\", "/")
    target = base if base.suffix == DOCX_SUFFIX else base.with_suffix(DOCX_SUFFIX)
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved = target.resolve()
    if not resolved.is_relative_to(_cwd().resolve()):
        raise ValueError("Chemin hors du répertoire autorisé.")
    return resolved


def _image_target(image_path: str) -> Path:
    _check(image_path)
    return _cwd() / image_path.replace("\\", "/")


def _load(filename: str) -> tuple[Document, Path]:
    target = _target(filename)
    if not target.exists():
        raise FileNotFoundError(f"Document introuvable : {target.name}")
    return Document(str(target)), target


server = MCPServer("word", version="1.0.0")


def _tool(name=None, description=None):
    def deco(fn):
        server.add_tool(fn, name=name, description=description)
        return fn

    return deco


@_tool(description="Crée un nouveau document Word vide et le sauvegarde.")
def create_document(filename: str) -> str:
    target = _target(filename)
    doc = Document()
    doc.save(str(target))
    return f"Document créé : {target.name}"


@_tool(description="Ajoute un paragraphe de texte au document.")
def add_paragraph(filename: str, text: str) -> str:
    doc, target = _load(filename)
    doc.add_paragraph(text)
    doc.save(str(target))
    return "Paragraphe ajouté."


@_tool(description="Ajoute un titre au document. level : 1 = titre principal, 2 = section, etc.")
def add_heading(filename: str, text: str, level: int = 1) -> str:
    doc, target = _load(filename)
    level = max(1, min(9, int(level)))
    doc.add_heading(text, level=level)
    doc.save(str(target))
    return f"Titre (niveau {level}) ajouté."


@_tool(description="Insère une image dans le document. width_em : largeur souhaitée en centimètres.")
def add_picture(filename: str, image_path: str, width_cm: float = 12.0) -> str:
    doc, target = _load(filename)
    img = _image_target(image_path)
    if not img.exists():
        raise FileNotFoundError(f"Image introuvable : {img.name}")
    doc.add_picture(str(img), width=Cm(float(width_cm)))
    doc.save(str(target))
    return "Image insérée."


@_tool(description="Ajoute un tableau avec des en-têtes et des lignes de données.")
def add_table(filename: str, headers: list[str], rows: list[list[str]]) -> str:
    doc, target = _load(filename)
    table = doc.add_table(rows=1, cols=max(1, len(headers)))
    table.style = "Table Grid"
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = str(header)
        for run in cell.paragraphs[0].runs:
            run.font.bold = True
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            if i < len(cells):
                cells[i].text = str(value)
    doc.save(str(target))
    return f"Tableau ajouté ({len(rows)} ligne(s))."


@_tool(description="Ajoute un saut de page au document.")
def add_page_break(filename: str) -> str:
    doc, target = _load(filename)
    doc.add_page_break()
    doc.save(str(target))
    return "Saut de page ajouté."


@_tool(description="Insère une liste numérotée après le paragraphe contenant after_text.")
def insert_numbered_list_near_text(filename: str, after_text: str, items: list[str]) -> str:
    doc, target = _load(filename)
    anchor = None
    for idx, para in enumerate(doc.paragraphs):
        if after_text in para.text:
            anchor = idx
            break
    if anchor is None:
        raise ValueError(f"Paragraphe contenant « {after_text} » introuvable.")
    for item in items:
        para = doc.add_paragraph(str(item), style="List Number")
        _ = para
    doc.save(str(target))
    return f"Liste numérotée insérée ({len(items)} élément(s))."


@_tool(description="Met en forme le paragraphe contenant exactement text (gras/italique/taille de police).")
def format_text(
    filename: str, text: str, bold: bool | None = None, italic: bool | None = None, font_size: int | None = None
) -> str:
    doc, target = _load(filename)
    found = False
    for para in doc.paragraphs:
        if para.text.strip() == text.strip():
            for run in para.runs:
                if bold is not None:
                    run.font.bold = bold
                if italic is not None:
                    run.font.italic = italic
                if font_size is not None:
                    run.font.size = Pt(float(font_size))
            if not para.runs:
                run = para.add_run(text)
                if bold is not None:
                    run.font.bold = bold
                if italic is not None:
                    run.font.italic = italic
                if font_size is not None:
                    run.font.size = Pt(float(font_size))
            found = True
            break
    if not found:
        raise ValueError(f"Paragraphe « {text} » non trouvé.")
    doc.save(str(target))
    return "Format appliqué."


@_tool(description="Ajuste la largeur des colonnes du premier tableau (list de largeurs en centimètres).")
def format_table(filename: str, column_widths: list[float]) -> str:
    doc, target = _load(filename)
    if not doc.tables:
        raise ValueError("Aucun tableau dans le document.")
    table = doc.tables[0]
    for i, width in enumerate(column_widths):
        if i >= len(table.columns):
            break
        for cell in table.columns[i].cells:
            cell.width = Cm(float(width))
    doc.save(str(target))
    return "Largeurs de colonne appliquées."


@_tool(description="Convertit le document .docx en PDF (LibreOffice en arrière-plan).")
async def convert_to_pdf(filename: str) -> str:
    from asyncio import create_subprocess_exec, create_subprocess_shell

    target = _target(filename)
    if not target.exists():
        raise FileNotFoundError(f"Document introuvable : {target.name}")
    proc = await create_subprocess_exec(
        "soffice",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(target.parent),
        str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    pdf_path = target.with_suffix(".pdf")
    if proc.returncode != 0 or not pdf_path.exists():
        raise RuntimeError(f"Conversion PDF échouée : {stderr.decode(errors='replace')[:300]}")
    return f"PDF généré : {pdf_path.name}"


@_tool(description="Retourne le texte intégral du document (paragraphes et tableaux).")
def get_document_text(filename: str) -> str:
    doc, _ = _load(filename)
    parts = [p.text for p in doc.paragraphs if p.text]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts) if parts else "(document vide)"


@_tool(description="Retourne la structure du document (titres par niveau).")
def get_document_outline(filename: str) -> str:
    doc, _ = _load(filename)
    lines = []
    for para in doc.paragraphs:
        if para.style.name.startswith("Heading") and para.text:
            level = para.style.name.replace("Heading ", "")
            lines.append(f"{'  ' * (int(level) - 1)}{para.text}")
    return "\n".join(lines) if lines else "(aucun titre)"


@_tool(description="Liste les documents .docx disponibles dans le dossier de travail.")
def list_available_documents() -> str:
    docs = sorted(str(p.relative_to(_cwd())) for p in _cwd().rglob(f"*{DOCX_SUFFIX}") if p.is_file())
    return "\n".join(docs) if docs else "(aucun document)"


def main() -> None:
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()