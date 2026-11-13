from datetime import datetime

import requests
import streamlit as st


API_URL = "http://127.0.0.1:8000/api"

FILE_TYPES = {
    "Image": ["png", "jpg", "jpeg"],
    "PDF": ["pdf"],
    "Word": ["docx"],
}


st.set_page_config(
    page_title="Tiah-QR",
    layout="centered",
)

# Ces valeurs survivent aux réexécutions de la page Streamlit.
DEFAULT_STATE = {
    "page": "home",
    "result": None,
    "form_version": 0,
    "delete_pending": None,
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


def api_request(method, path, **kwargs):
    """Appeler Tornado et traduire les erreurs en messages lisibles."""
    try:
        response = requests.request(
            method,
            f"{API_URL}{path}",
            timeout=30,
            **kwargs,
        )
    except requests.exceptions.ConnectionError as error:
        raise RuntimeError(
            "Impossible de joindre Tornado. Lancez : python server.py"
        ) from error
    except requests.exceptions.Timeout as error:
        raise RuntimeError(
            "Le serveur met trop de temps à répondre."
        ) from error
    except requests.exceptions.RequestException as error:
        raise RuntimeError(
            "Une erreur de communication est survenue."
        ) from error

    if not response.ok:
        try:
            message = response.json().get(
                "error",
                "La demande a échoué.",
            )
        except ValueError:
            message = f"Erreur serveur : {response.status_code}."

        raise RuntimeError(message)

    return response


def navigate(page):
    """Changer d'écran et réinitialiser les confirmations."""
    st.session_state.page = page
    st.session_state.delete_pending = None
    st.rerun()


def reset_creation():
    """Repartir d'un formulaire vide, sans supprimer l'historique."""
    st.session_state.result = None
    st.session_state.form_version += 1
    navigate("create")


def display_date(value):
    return datetime.fromisoformat(value).strftime("%d/%m/%Y à %H:%M")


def show_home():
    st.title("Tiah-QR")
    st.write("Transformez votre texte ou partagez vos fichiers.")
    st.divider()

    if st.button(
        "Créer un QR code",
        type="primary",
        use_container_width=True,
    ):
        reset_creation()

    if st.button("Historique", use_container_width=True):
        navigate("history")

    st.caption("Texte · Image · PDF · Word")


def show_result():
    entry = st.session_state.result
    image = api_request("GET", f"/qr/{entry['id']}").content

    st.success("Votre QR code est prêt.")
    st.image(image, width=280)

    st.write(entry["label"])
    st.caption(f"Type : {entry['kind']}")

    st.download_button(
        "Télécharger le QR",
        data=image,
        file_name=f"tiah-qr-{entry['id'][:8]}.png",
        mime="image/png",
        type="primary",
    )

    if entry["kind"] != "Texte":
        st.info(
            "Ce QR contient un lien. Le serveur doit rester accessible "
            "pour ouvrir le fichier."
        )
        st.code(entry["payload"], language=None)

    left, right = st.columns(2)

    with left:
        if st.button("Créer un autre QR"):
            reset_creation()

    with right:
        if st.button("Voir l'historique"):
            navigate("history")


def show_creation():
    if st.button("Retour à l'accueil"):
        navigate("home")

    st.title("Créer un QR code")

    if st.session_state.result is not None:
        show_result()
        return

    version = st.session_state.form_version

    # Le choix reste hors du formulaire pour afficher immédiatement
    # la zone de saisie ou d'import correspondante.
    kind = st.radio(
        "Quel contenu souhaitez-vous utiliser ?",
        ["Texte", "Image", "PDF", "Word"],
        index=None,
        horizontal=True,
        key=f"kind_{version}",
    )

    if kind is None:
        st.info("Choisissez un type de contenu pour commencer.")
        return

    with st.form(f"creation_{version}_{kind}"):
        text = ""
        uploaded = None

        if kind == "Texte":
            text = st.text_area(
                "Votre texte",
                placeholder="Écrivez votre message ici…",
                height=150,
            )
            st.caption("Maximum : 1 000 octets UTF-8.")

        else:
            uploaded = st.file_uploader(
                f"Importer votre fichier : {kind}",
                type=FILE_TYPES[kind],
                accept_multiple_files=False,
            )

            st.caption("Taille maximale : 5 Mo.")

            if uploaded is not None and kind == "Image":
                st.image(uploaded, caption="Aperçu", width=220)

            st.info(
                "Le fichier sera conservé sur ce serveur. "
                "Toute personne disposant de son lien pourra y accéder."
            )

        st.subheader("Personnaliser")

        color = st.color_picker(
            "Couleur du QR",
            value="#386280",
        )

        st.caption("Le fond reste blanc. Choisissez une couleur foncée.")

        submitted = st.form_submit_button(
            "Générer le QR code",
            type="primary",
        )

    if not submitted:
        return

    if kind == "Texte" and not text.strip():
        st.warning("Saisissez un texte.")
        return

    if kind != "Texte" and uploaded is None:
        st.warning("Importez un fichier.")
        return

    data = {
        "kind": kind,
        "color": color,
        "text": text,
    }

    files = None

    if uploaded is not None:
        files = {
            "file": (
                uploaded.name,
                uploaded.getvalue(),
                "application/octet-stream",
            )
        }

    with st.spinner("Génération en cours…"):
        entry = api_request(
            "POST",
            "/create",
            data=data,
            files=files,
        ).json()

    st.session_state.result = entry
    st.rerun()


def show_history():
    if st.button("Retour à l'accueil"):
        navigate("home")

    st.title("Historique")

    items = api_request("GET", "/history").json()["items"]

    if not items:
        st.info("Votre historique est vide.")

        if st.button("Créer votre premier QR", type="primary"):
            reset_creation()

        return

    st.caption(f"{len(items)} QR code(s) enregistré(s).")

    for entry in items:
        entry_id = entry["id"]

        with st.container(border=True):
            picture, details = st.columns([1, 3])

            # Charger chaque image depuis Tornado, pas depuis le disque.
            image = None

            try:
                image = api_request(
                    "GET",
                    f"/qr/{entry_id}",
                ).content
            except RuntimeError:
                pass

            with picture:
                if image is not None:
                    st.image(image, width=110)
                else:
                    st.caption("Image indisponible")

            with details:
                # st.text évite d'interpréter le nom comme du Markdown.
                st.text(entry["label"])

                st.caption(
                    f"{entry['kind']} · "
                    f"{display_date(entry['created_at'])}"
                )

                if image is not None:
                    st.download_button(
                        "Télécharger",
                        data=image,
                        file_name=f"tiah-qr-{entry_id[:8]}.png",
                        mime="image/png",
                        key=f"download_{entry_id}",
                    )

                if st.button(
                    "Supprimer",
                    key=f"delete_{entry_id}",
                ):
                    st.session_state.delete_pending = entry_id

            if st.session_state.delete_pending == entry_id:
                message = "Supprimer ce QR de l'historique ?"

                if entry["kind"] != "Texte":
                    message = (
                        "Supprimer ce QR et son fichier ? "
                        "Les copies partagées ne permettront plus "
                        "d'accéder au fichier depuis Tiah-QR."
                    )

                st.warning(message)

                confirm, cancel = st.columns(2)

                with confirm:
                    if st.button(
                        "Confirmer la suppression",
                        key=f"confirm_{entry_id}",
                    ):
                        api_request(
                            "DELETE",
                            f"/history/{entry_id}",
                        )

                        result = st.session_state.result

                        if result and result["id"] == entry_id:
                            st.session_state.result = None

                        st.session_state.delete_pending = None
                        st.rerun()

                with cancel:
                    if st.button(
                        "Annuler",
                        key=f"cancel_{entry_id}",
                    ):
                        st.session_state.delete_pending = None
                        st.rerun()


try:
    if st.session_state.page == "home":
        show_home()
    elif st.session_state.page == "create":
        show_creation()
    else:
        show_history()

except RuntimeError as error:
    st.error(str(error))