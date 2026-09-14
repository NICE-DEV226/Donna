"""Serveur MCP Excel — classeurs .xlsx via openpyxl.

Dialogue avec le client sur stdio (MCP). Les noms de fichiers arrivent déjà
namespacés par tenant (<tenant>/<fichier>, voir McpBridgeService) et sont
résolus relativement au répertoire de travail (cwd = data/mcp_documents/excel).
Défense en profondeur : la traversée de répertoire reste refusée ici.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from openpyxl import Workbook, load_workbook

from mcp.server.mcpserver import MCPServer

XLSX_SUFFIX = ".xlsx"
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._\-\u00A0-\uFFFF]+$")


def _cwd() -> Path:
    return Path.cwd()


def _check(value: str) -> None:
    if not value or value.startswith(("/", "\\")):
        raise ValueError(f"Nom de fichier invalide (chemin absolu) : « {value} »")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        raise ValueError(f"Nom de fichier invalide (schéma URL) : « {value} »")
    parts = value.replace("\\", "/").split("/")
    if ".." in parts or len(parts) > 2:
        raise ValueError(f"Nom de fichier invalide (traversée) : « {value} »")
    if any(not p or p == "." or not SAFE_NAME_RE.fullmatch(p) for p in parts):
        raise ValueError(f"Nom de fichier invalide (caractères) : « {value} »")


def _target(filename: str) -> Path:
    _check(filename)
    base = _cwd() / filename.replace("\\", "/")
    target = base if base.suffix == XLSX_SUFFIX else base.with_suffix(XLSX_SUFFIX)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.resolve().is_relative_to(_cwd().resolve()):
        raise ValueError("Chemin hors du répertoire autorisé.")
    return target


def _load(filename: str):
    target = _target(filename)
    if not target.exists():
        raise FileNotFoundError(f"Classeur introuvable : {target.name}")
    return load_workbook(str(target)), target


server = MCPServer("excel", version="1.0.0")


def _tool(name=None, description=None):
    def deco(fn):
        server.add_tool(fn, name=name, description=description)
        return fn

    return deco


@_tool(description="Crée un nouveau classeur Excel vide (feuille Sheet1) et le sauvegarde.")
def EXCEL_MCP_create_workbook(filename: str) -> str:
    target = _target(filename)
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    wb.save(str(target))
    return f"Classeur créé : {target.name}"


@_tool(description="Écrit une matrice de données dans la feuille indiquée (cases depuis A1). data = liste de lignes.")
def EXCEL_MCP_write_workbook_data(
    filename: str,
    data: list[list],
    sheet_name: str = "Sheet1",
) -> str:
    wb, target = _load(filename)
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.create_sheet(sheet_name)
    for row in data:
        ws.append(list(row))
    wb.save(str(target))
    return f"{len(data)} ligne(s) écrites dans « {ws.title} »."


@_tool(description="Crée une nouvelle feuille de calcul dans le classeur.")
def EXCEL_MCP_create_worksheet(filename: str, sheet_name: str) -> str:
    wb, target = _load(filename)
    if sheet_name in wb.sheetnames:
        raise ValueError(f"Feuille « {sheet_name} » déjà présente.")
    wb.create_sheet(sheet_name)
    wb.save(str(target))
    return f"Feuille « {sheet_name} » créée."


@_tool(description="Fusionne une plage de cellules (indices 1-based). Ex : start_row=1, start_col=1, end_row=1, end_col=3.")
def EXCEL_MCP_merge_cells(
    filename: str,
    sheet_name: str,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
) -> str:
    wb, target = _load(filename)
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"Feuille « {sheet_name} » introuvable.")
    ws = wb[sheet_name]
    ws.merge_cells(
        start_row=int(start_row),
        start_column=int(start_col),
        end_row=int(end_row),
        end_column=int(end_col),
    )
    wb.save(str(target))
    return "Plage fusionnée."


@_tool(description="Retourne les infos du classeur : feuilles, dimensions, données de chaque feuille.")
def EXCEL_MCP_get_workbook_info(filename: str) -> str:
    wb, target = _load(filename)
    lines = [f"Classeur : {target.name}", f"Feuilles : {', '.join(wb.sheetnames)}"]
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        lines.append(f"- {sheet} : {ws.max_row} ligne(s) x {ws.max_column} colonne(s)")
    return "\n".join(lines)


def main() -> None:
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()