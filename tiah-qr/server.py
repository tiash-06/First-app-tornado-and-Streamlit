import asyncio
import json
import logging
import os
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

import qrcode
import tornado.web
from PIL import Image, UnidentifiedImageError
from qrcode.exceptions import DataOverflowError

from storage import (
    QR_DIR,
    UPLOADS_DIR,
    add_entry,
    delete_entry,
    find_entry,
    initialize_storage,
    load_history,
)


MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_TEXT_BYTES = 1000

# Pour un téléphone, remplacer localhost par l'adresse réseau du PC.
FILE_BASE_URL = os.getenv(
    "TIAH_FILE_BASE_URL",
    "http://127.0.0.1:8001",
).rstrip("/")

ALLOWED_EXTENSIONS = {
    "Image": {".png", ".jpg", ".jpeg"},
    "PDF": {".pdf"},
    "Word": {".docx"},
}


def validate_color(color):
    """Valider une couleur et imposer un contraste minimal sur fond blanc."""
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("La couleur choisie est invalide.")

    channels = [
        int(color[index:index + 2], 16) / 255
        for index in (1, 3, 5)
    ]

    linear = [
        value / 12.92
        if value <= 0.04045
        else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]

    luminance = (
        0.2126 * linear[0]
        + 0.7152 * linear[1]
        + 0.0722 * linear[2]
    )

    contrast = 1.05 / (luminance + 0.05)

    # Garde-fou de notre application, pas une garantie de lecture du QR.
    if contrast < 4.5:
        raise ValueError(
            "Cette couleur est trop claire. Choisissez une couleur plus foncée."
        )


def validate_file(kind, filename, content):
    """Contrôler l'extension, la taille et la structure de base du fichier."""
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS[kind]:
        raise ValueError("Ce format ne correspond pas au type sélectionné.")

    if not content:
        raise ValueError("Le fichier est vide.")

    if len(content) > MAX_FILE_SIZE:
        raise ValueError("Le fichier dépasse la limite de 5 Mo.")

    if kind == "Image":
        try:
            with Image.open(BytesIO(content)) as image:
                expected = "PNG" if extension == ".png" else "JPEG"

                if image.format != expected:
                    raise ValueError(
                        "Le contenu de l'image ne correspond pas à son extension."
                    )

                image.verify()
        except (
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            Image.DecompressionBombError,
        ) as error:
            raise ValueError("L'image est invalide ou trop volumineuse.") from error

    elif kind == "PDF":
        if not content.startswith(b"%PDF-"):
            raise ValueError("Ce fichier ne semble pas être un PDF.")

    elif kind == "Word":
        try:
            with ZipFile(BytesIO(content)) as document:
                names = set(document.namelist())

                if not {
                    "[Content_Types].xml",
                    "word/document.xml",
                }.issubset(names):
                    raise ValueError("Ce fichier ne semble pas être un DOCX.")
        except BadZipFile as error:
            raise ValueError("Le fichier Word est invalide.") from error

    return extension


def generate_png(content, color):
    """Créer un QR avec une marge blanche de quatre modules."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )

    qr.add_data(content)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color=color,
        back_color="white",
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")

    return buffer.getvalue()


class APIHandler(tornado.web.RequestHandler):
    """Donner aux erreurs de l'API un format JSON lisible par Streamlit."""

    def set_default_headers(self):
        self.set_header("Cache-Control", "no-store")

    def write_error(self, status_code, **kwargs):
        message = "Une erreur serveur est survenue."

        if "exc_info" in kwargs:
            error = kwargs["exc_info"][1]

            if isinstance(error, tornado.web.HTTPError):
                message = error.reason or message

        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps({"error": message}, ensure_ascii=False))


class CreateHandler(APIHandler):
    def post(self):
        kind = self.get_body_argument("kind", "")
        color = self.get_body_argument("color", "#000000")

        upload_content = None
        upload_name = None

        try:
            validate_color(color)

            if kind == "Texte":
                text = self.get_body_argument("text", "").strip()

                if not text:
                    raise ValueError("Saisissez un texte.")

                if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
                    raise ValueError(
                        "Le texte dépasse la limite de 1 000 octets UTF-8."
                    )

                payload = text
                label = text[:70]

            elif kind in ALLOWED_EXTENSIONS:
                files = self.request.files.get("file", [])

                if len(files) != 1:
                    raise ValueError("Importez un seul fichier.")

                uploaded = files[0]
                upload_content = uploaded["body"]

                extension = validate_file(
                    kind,
                    uploaded["filename"],
                    upload_content,
                )

                upload_name = f"{uuid4().hex}{extension}"
                payload = f"{FILE_BASE_URL}/files/{upload_name}"

                # Nettoyer le nom affiché, sans l'utiliser pour le stockage.
                label = Path(
                    uploaded["filename"].replace("\\", "/")
                ).name[:150]

            else:
                raise ValueError("Choisissez un type de contenu.")

            png = generate_png(payload, color)

        except (ValueError, DataOverflowError) as error:
            raise tornado.web.HTTPError(400, reason=str(error)) from error

        entry_id = uuid4().hex
        qr_name = f"{entry_id}.png"

        entry = {
            "id": entry_id,
            "kind": kind,
            "label": label,
            "created_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "color": color,
            "payload": payload,
            "qr_file": qr_name,
            "upload_file": upload_name,
        }

        # En cas d'échec d'enregistrement, retirer les fichiers incomplets.
        try:
            if upload_name:
                (UPLOADS_DIR / upload_name).write_bytes(upload_content)

            (QR_DIR / qr_name).write_bytes(png)
            add_entry(entry)

        except Exception:
            (QR_DIR / qr_name).unlink(missing_ok=True)

            if upload_name:
                (UPLOADS_DIR / upload_name).unlink(missing_ok=True)

            raise

        self.set_status(201)
        self.write(entry)


class HistoryHandler(APIHandler):
    def get(self):
        self.write({"items": load_history()})


class EntryHandler(APIHandler):
    def delete(self, entry_id):
        if not delete_entry(entry_id):
            raise tornado.web.HTTPError(404, reason="QR introuvable.")

        self.write({"deleted": True})


class QRImageHandler(APIHandler):
    def get(self, entry_id):
        entry = find_entry(entry_id)

        if entry is None:
            raise tornado.web.HTTPError(404, reason="QR introuvable.")

        path = QR_DIR / entry["qr_file"]

        if not path.exists():
            raise tornado.web.HTTPError(404, reason="Image QR introuvable.")

        self.set_header("Content-Type", "image/png")
        self.finish(path.read_bytes())


class DocumentHandler(tornado.web.StaticFileHandler):
    def set_extra_headers(self, path):
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Cache-Control", "no-store")


async def main():
    initialize_storage()

    api = tornado.web.Application([
        (r"/api/create", CreateHandler),
        (r"/api/history", HistoryHandler),
        (r"/api/history/([a-f0-9]{32})", EntryHandler),
        (r"/api/qr/([a-f0-9]{32})", QRImageHandler),
    ])

    documents = tornado.web.Application([
        (
            r"/files/([a-f0-9]{32}\.(?:png|jpg|jpeg|pdf|docx))",
            DocumentHandler,
            {"path": str(UPLOADS_DIR)},
        ),
    ])

    api.listen(
        8000,
        address="127.0.0.1",
        max_body_size=6 * 1024 * 1024,
    )

    documents.listen(8001, address="0.0.0.0")

    print("API : http://127.0.0.1:8000")
    print(f"Adresse utilisée dans les QR fichiers : {FILE_BASE_URL}")
    print("Arrêter le serveur : Ctrl+C")

    await asyncio.Event().wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass