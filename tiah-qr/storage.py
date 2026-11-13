import json
from pathlib import Path


#mba ahafahana miconservez an le chein an le terminal .
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
QR_DIR = DATA_DIR / "qrcodes"
HISTORY_FILE = DATA_DIR / "history.json"


def initialize_storage():
    """Créer les dossiers et un historique vide au premier démarrage."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    QR_DIR.mkdir(parents=True, exist_ok=True)

    if not HISTORY_FILE.exists():
        save_history([])


def load_history():
    """Lire l'historique sans écraser silencieusement un fichier abîmé."""
    with HISTORY_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_history(items):
    """Remplacer le JSON après avoir écrit un fichier temporaire complet."""
    temporary_file = HISTORY_FILE.with_suffix(".tmp")

    temporary_file.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    temporary_file.replace(HISTORY_FILE)


def add_entry(entry):
    """Ajouter le résultat le plus récent en tête de liste."""
    items = load_history()
    items.insert(0, entry)
    save_history(items)


def find_entry(entry_id):
    """Retrouver un élément grâce à son identifiant."""
    return next(
        (item for item in load_history() if item["id"] == entry_id),
        None,
    )


def delete_entry(entry_id):
    """Retirer l'entrée puis supprimer ses fichiers associés."""
    items = load_history()
    entry = next(
        (item for item in items if item["id"] == entry_id),
        None,
    )

    if entry is None:
        return False

    save_history([item for item in items if item["id"] != entry_id])

    (QR_DIR / entry["qr_file"]).unlink(missing_ok=True)

    if entry.get("upload_file"):
        (UPLOADS_DIR / entry["upload_file"]).unlink(missing_ok=True)

    return True