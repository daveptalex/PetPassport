from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import secrets
import uuid
import zipfile
from copy import deepcopy
from pathlib import Path
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable

import segno

SCHEMA_VERSION = 1
DATA_KEY = "pt.petpassport.data.v1"
PIN_KEY = "pt.petpassport.pin.v1"
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


# -----------------------------
# Data model helpers
# -----------------------------

def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def today_iso() -> str:
    return date.today().isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def default_owner() -> dict[str, Any]:
    return {
        "name": "",
        "photo_b64": "",
        "address": "",
        "country": "Portugal",
        "phone": "",
        "alt_phone": "",
        "email": "",
        "emergency_contact": "",
    }


def default_settings() -> dict[str, Any]:
    return {
        "theme": "system",
        "language": "pt-PT",
        "biometric_enabled": False,
        "medical_disclaimer_seen": False,
    }


def default_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "settings": default_settings(),
        "owner": default_owner(),
        "pets": [],
    }


def empty_pet() -> dict[str, Any]:
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "name": "",
        "photo_b64": "",
        "photo_path": "",
        "photo_name": "",
        "species": "Cão",
        "breed": "",
        "secondary_breed": "",
        "sex": "",
        "birth_date": "",
        "color": "",
        "coat": "",
        "current_weight": "",
        "reproductive_status": "",
        "neutered": False,
        "distinctive_features": "",
        "microchip": {
            "number": "",
            "implant_date": "",
            "implant_location": "",
            "country": "Portugal",
            "registry": "",
            "veterinarian": "",
        },
        "veterinary": {
            "clinic": "",
            "veterinarian": "",
            "address": "",
            "phone": "",
            "email": "",
            "website": "",
            "hours": "",
            "emergency_phone": "",
        },
        "insurance": {
            "company": "",
            "policy": "",
            "coverage": "",
            "start_date": "",
            "renewal_date": "",
            "contact": "",
            "deductible": "",
            "notes": "",
        },
        "lost_mode": {
            "active": False,
            "public_phone": "",
            "message": "",
            "last_seen_place": "",
            "last_seen_date": "",
        },
        "vaccines": [],
        "medications": [],
        "appointments": [],
        "weights": [],
        "parasite_treatments": [],
        "allergies": [],
        "conditions": [],
        "surgeries": [],
        "exams": [],
        "documents": [],
        "travels": [],
        "reminders": [],
    }


def ensure_state_shape(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return default_state()
    base = default_state()
    base.update(state)
    if not isinstance(base.get("settings"), dict):
        base["settings"] = default_settings()
    else:
        merged = default_settings()
        merged.update(base["settings"])
        base["settings"] = merged
    if not isinstance(base.get("owner"), dict):
        base["owner"] = default_owner()
    else:
        merged = default_owner()
        merged.update(base["owner"])
        base["owner"] = merged
    pets = []
    for p in base.get("pets", []) if isinstance(base.get("pets"), list) else []:
        if not isinstance(p, dict):
            continue
        ep = empty_pet()
        ep.update(p)
        for k in ("microchip", "veterinary", "insurance", "lost_mode"):
            if not isinstance(ep.get(k), dict):
                ep[k] = empty_pet()[k]
            else:
                merged = empty_pet()[k]
                merged.update(ep[k])
                ep[k] = merged
        for k in (
            "vaccines", "medications", "appointments", "weights",
            "parasite_treatments", "allergies", "conditions", "surgeries",
            "exams", "documents", "travels", "reminders",
        ):
            if not isinstance(ep.get(k), list):
                ep[k] = []
        pets.append(ep)
    base["pets"] = pets
    base["schema_version"] = SCHEMA_VERSION
    return base


def age_text(birth_date: str) -> str:
    d = parse_date(birth_date)
    if not d:
        return "Idade não indicada"
    today = date.today()
    years = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    if years <= 0:
        months = (today.year - d.year) * 12 + today.month - d.month
        return f"{max(months, 0)} meses"
    return f"{years} anos"


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def normalize_date(value: str | None) -> str:
    d = parse_date(value)
    return d.isoformat() if d else (value or "").strip()


def human_date(value: str | None) -> str:
    d = parse_date(value)
    return d.strftime("%d/%m/%Y") if d else (value or "—")


def safe_filename(value: str, fallback: str = "ficheiro") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or fallback


def find_pet(state: dict[str, Any], pet_id: str | None) -> dict[str, Any] | None:
    if not pet_id:
        return None
    for pet in state.get("pets", []):
        if pet.get("id") == pet_id:
            return pet
    return None


def touch(obj: dict[str, Any]) -> None:
    obj["updated_at"] = now_iso()


def make_record(**kwargs: Any) -> dict[str, Any]:
    rec = {"id": new_id(), "created_at": now_iso(), "updated_at": now_iso()}
    rec.update(kwargs)
    return rec


def upsert_record(pet: dict[str, Any], collection: str, record: dict[str, Any]) -> None:
    items = pet.setdefault(collection, [])
    rid = record.get("id")
    for i, existing in enumerate(items):
        if existing.get("id") == rid:
            record["updated_at"] = now_iso()
            items[i] = record
            touch(pet)
            return
    if not rid:
        record["id"] = new_id()
    record.setdefault("created_at", now_iso())
    record["updated_at"] = now_iso()
    items.append(record)
    touch(pet)


def delete_record(pet: dict[str, Any], collection: str, record_id: str) -> None:
    pet[collection] = [x for x in pet.get(collection, []) if x.get("id") != record_id]
    touch(pet)


# -----------------------------
# PIN helpers
# -----------------------------

def make_pin_hash(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 220_000)
    return "pbkdf2_sha256$220000$%s$%s" % (
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_pin(pin: str, encoded: str) -> bool:
    try:
        algo, rounds_s, salt_s, digest_s = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_s)
        salt = base64.urlsafe_b64decode(salt_s.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_s.encode("ascii"))
        got = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, rounds)
        return secrets.compare_digest(got, expected)
    except Exception:
        return False


# -----------------------------
# Dashboard and timeline
# -----------------------------

def upcoming_events(pet: dict[str, Any], days: int = 365) -> list[dict[str, str]]:
    today = date.today()
    limit = today + timedelta(days=days)
    events: list[dict[str, str]] = []

    def add(dt: str, title: str, kind: str, subtitle: str = "") -> None:
        d = parse_date(dt)
        if d and today <= d <= limit:
            events.append({
                "date": d.isoformat(),
                "title": title,
                "kind": kind,
                "subtitle": subtitle,
            })

    for v in pet.get("vaccines", []):
        add(v.get("next_due", "") or v.get("valid_until", ""), f"Vacina: {v.get('name', 'vacina')}", "Vacina", v.get("disease", ""))
    for a in pet.get("appointments", []):
        add(a.get("date", ""), f"Consulta: {a.get('reason', 'veterinária')}", "Consulta", a.get("clinic", ""))
    for p in pet.get("parasite_treatments", []):
        add(p.get("next_due", ""), f"Desparasitação: {p.get('product', '')}", "Desparasitação", p.get("category", ""))
    for r in pet.get("reminders", []):
        add(r.get("date", ""), r.get("title", "Lembrete"), r.get("category", "Lembrete"), r.get("notes", ""))
    for t in pet.get("travels", []):
        add(t.get("departure", ""), f"Viagem: {t.get('destination', '')}", "Viagem", t.get("country", ""))
    ins = pet.get("insurance", {})
    add(ins.get("renewal_date", ""), "Renovação do seguro", "Seguro", ins.get("company", ""))

    events.sort(key=lambda x: x["date"])
    return events


def active_medications(pet: dict[str, Any]) -> list[dict[str, Any]]:
    today = date.today()
    result = []
    for m in pet.get("medications", []):
        start = parse_date(m.get("start_date"))
        end = parse_date(m.get("end_date"))
        if (not start or start <= today) and (not end or today <= end):
            result.append(m)
    return result


def build_timeline(pet: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []

    def push(collection: str, kind: str, date_field: str, title_fn) -> None:
        for r in pet.get(collection, []):
            d = r.get(date_field, "")
            parsed = parse_date(d)
            if parsed:
                items.append({
                    "date": parsed.isoformat(),
                    "kind": kind,
                    "title": title_fn(r),
                    "record_id": r.get("id", ""),
                    "collection": collection,
                })

    push("appointments", "Consulta", "date", lambda r: r.get("reason", "Consulta veterinária"))
    push("weights", "Peso", "date", lambda r: f"Peso: {r.get('weight', '')} kg")
    push("vaccines", "Vacina", "date", lambda r: r.get("name", "Vacina"))
    push("parasite_treatments", "Desparasitação", "date", lambda r: r.get("product", "Desparasitação"))
    push("surgeries", "Cirurgia", "date", lambda r: r.get("procedure", "Cirurgia"))
    push("exams", "Exame", "date", lambda r: r.get("type", "Exame"))
    push("conditions", "Condição", "date", lambda r: r.get("name", "Condição médica"))
    push("travels", "Viagem", "departure", lambda r: r.get("destination", "Viagem"))
    items.sort(key=lambda x: x["date"], reverse=True)
    return items


def search_state(state: dict[str, Any], query: str) -> list[dict[str, str]]:
    q = query.strip().casefold()
    if not q:
        return []
    results: list[dict[str, str]] = []
    for pet in state.get("pets", []):
        pet_name = pet.get("name", "Animal")
        for field in ("name", "species", "breed", "color", "distinctive_features"):
            val = str(pet.get(field, ""))
            if q in val.casefold():
                results.append({"pet_id": pet.get("id", ""), "section": "Perfil", "title": val or pet_name, "subtitle": field})
        chip = str(pet.get("microchip", {}).get("number", ""))
        if q in chip.casefold() and chip:
            results.append({"pet_id": pet.get("id", ""), "section": "Microchip", "title": chip, "subtitle": pet_name})
        mapping = {
            "vaccines": ("Vacinas", ["name", "disease", "manufacturer", "lot", "veterinarian", "clinic", "notes"]),
            "medications": ("Medicação", ["name", "active_ingredient", "dose", "frequency", "veterinarian", "notes"]),
            "appointments": ("Consultas", ["clinic", "veterinarian", "reason", "symptoms", "diagnosis", "treatment", "notes"]),
            "allergies": ("Alergias", ["name", "type", "reaction", "severity", "treatment", "notes"]),
            "conditions": ("Condições", ["name", "veterinarian", "treatment", "notes"]),
            "surgeries": ("Cirurgias", ["procedure", "clinic", "veterinarian", "reason", "recovery", "notes"]),
            "exams": ("Exames", ["type", "clinic", "veterinarian", "result", "notes"]),
            "documents": ("Documentos", ["name", "category", "notes"]),
            "travels": ("Viagens", ["destination", "country", "transport", "accommodation", "notes"]),
            "reminders": ("Lembretes", ["title", "category", "notes"]),
        }
        for collection, (section, fields) in mapping.items():
            for rec in pet.get(collection, []):
                text = " | ".join(str(rec.get(f, "")) for f in fields)
                if q in text.casefold():
                    results.append({
                        "pet_id": pet.get("id", ""),
                        "section": section,
                        "title": str(rec.get(fields[0], section)) or section,
                        "subtitle": pet_name,
                    })
    return results[:100]


# -----------------------------
# QR
# -----------------------------

def emergency_text(pet: dict[str, Any], owner: dict[str, Any]) -> str:
    allergies = ", ".join(a.get("name", "") for a in pet.get("allergies", []) if a.get("name")) or "Nenhuma registada"
    conditions = ", ".join(c.get("name", "") for c in pet.get("conditions", []) if c.get("name")) or "Nenhuma registada"
    meds = ", ".join(m.get("name", "") for m in active_medications(pet) if m.get("name")) or "Nenhuma registada"
    phone = pet.get("lost_mode", {}).get("public_phone") or owner.get("phone", "")
    lost = pet.get("lost_mode", {})
    lines = [
        "PET PASSPORT - EMERGÊNCIA",
        f"Nome: {pet.get('name', '')}",
        f"Espécie: {pet.get('species', '')}",
        f"Raça: {pet.get('breed', '')}",
        f"Microchip: {pet.get('microchip', {}).get('number', '')}",
        f"Alergias: {allergies}",
        f"Condições: {conditions}",
        f"Medicação atual: {meds}",
        f"Contacto: {phone}",
    ]
    if lost.get("active"):
        lines.extend([
            "ANIMAL PERDIDO",
            f"Mensagem: {lost.get('message', '')}",
            f"Último local: {lost.get('last_seen_place', '')}",
            f"Data: {lost.get('last_seen_date', '')}",
        ])
    return "\n".join(lines)


def make_qr_svg_bytes(text: str) -> bytes:
    qr = segno.make(text, error="m")
    out = io.BytesIO()
    qr.save(out, kind="svg", scale=5, border=2, dark="#245C51", light="#FFFFFF")
    return out.getvalue()


# -----------------------------
# PDF export (stdlib-only writer)
# -----------------------------

def _pdf_escape(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    raw = raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return raw


def _wrap_text(text: str, width: int = 88) -> list[str]:
    words = str(text).replace("\r", "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def make_simple_pdf(title: str, lines: Iterable[str]) -> bytes:
    prepared: list[str] = [title, ""]
    for line in lines:
        prepared.extend(_wrap_text(str(line)))
    lines_per_page = 48
    pages = [prepared[i:i + lines_per_page] for i in range(0, len(prepared), lines_per_page)] or [[title]]

    objects: list[bytes] = []
    # 1 catalog, 2 pages, 3 font
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_refs = []
    for i in range(len(pages)):
        page_refs.append(f"{4 + i * 2} 0 R")
    objects.append(("<< /Type /Pages /Kids [" + " ".join(page_refs) + f"] /Count {len(pages)} >>").encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

    for idx, page_lines in enumerate(pages):
        page_obj_num = 4 + idx * 2
        content_obj_num = page_obj_num + 1
        page_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj_num} 0 R >>"
        ).encode("ascii")
        content = bytearray()
        content.extend(b"BT\n/F1 11 Tf\n50 795 Td\n15 TL\n")
        for li, line in enumerate(page_lines):
            if li == 0:
                content.extend(b"/F1 18 Tf\n")
            elif li == 1:
                content.extend(b"/F1 11 Tf\n")
            content.extend(b"(")
            content.extend(_pdf_escape(line))
            content.extend(b") Tj\nT*\n")
        content.extend(b"ET")
        stream = b"<< /Length %d >>\nstream\n" % len(content) + bytes(content) + b"\nendstream"
        objects.extend([page_obj, stream])

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def pet_report_lines(pet: dict[str, Any], owner: dict[str, Any]) -> list[str]:
    lines = [
        f"Nome: {pet.get('name', '')}",
        f"Espécie: {pet.get('species', '')}",
        f"Raça: {pet.get('breed', '')}",
        f"Sexo: {pet.get('sex', '')}",
        f"Nascimento: {human_date(pet.get('birth_date'))}",
        f"Microchip: {pet.get('microchip', {}).get('number', '')}",
        f"Tutor: {owner.get('name', '')}",
        f"Contacto: {owner.get('phone', '')}",
        "",
        "VACINAS",
    ]
    for v in sorted(pet.get("vaccines", []), key=lambda x: x.get("date", ""), reverse=True):
        lines.append(
            f"- {v.get('name', '')} | doença: {v.get('disease', '')} | data: {human_date(v.get('date'))} | válida até: {human_date(v.get('valid_until'))} | próxima: {human_date(v.get('next_due'))}"
        )
    lines.extend(["", "MEDICAÇÃO ATUAL"])
    for m in active_medications(pet):
        lines.append(f"- {m.get('name', '')} | dose: {m.get('dose', '')} | frequência: {m.get('frequency', '')} | horários: {m.get('times', '')}")
    lines.extend(["", "ALERGIAS"])
    for a in pet.get("allergies", []):
        lines.append(f"- {a.get('name', '')} | reação: {a.get('reaction', '')} | gravidade: {a.get('severity', '')}")
    lines.extend(["", "CONDIÇÕES MÉDICAS"])
    for c in pet.get("conditions", []):
        lines.append(f"- {c.get('name', '')} | tratamento: {c.get('treatment', '')}")
    lines.extend(["", "CONSULTAS RECENTES"])
    for a in sorted(pet.get("appointments", []), key=lambda x: x.get("date", ""), reverse=True)[:10]:
        lines.append(f"- {human_date(a.get('date'))}: {a.get('reason', '')} | {a.get('clinic', '')} | {a.get('diagnosis', '')}")
    lines.extend(["", "Aviso: este documento é um resumo administrativo e não constitui diagnóstico nem aconselhamento veterinário."])
    return lines


def make_pet_pdf(pet: dict[str, Any], owner: dict[str, Any]) -> bytes:
    return make_simple_pdf(f"Pet Passport — {pet.get('name', 'Animal')}", pet_report_lines(pet, owner))


# -----------------------------
# Attachment storage
# -----------------------------

def app_storage_dir() -> Path:
    root = os.environ.get("FLET_APP_STORAGE_DATA", "").strip()
    if root:
        base = Path(root)
    else:
        base = Path.cwd() / ".pet_passport_data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def store_attachment_bytes(data: bytes, original_name: str) -> str:
    folder = app_storage_dir() / "attachments"
    folder.mkdir(parents=True, exist_ok=True)
    ext = Path(original_name).suffix[:12]
    path = folder / f"{new_id()}{ext}"
    path.write_bytes(data)
    return str(path)


def read_pet_photo_bytes(pet: dict[str, Any]) -> bytes:
    b64 = pet.get("photo_b64", "")
    if b64:
        return base64.b64decode(b64)
    path = str(pet.get("photo_path", "") or "")
    if path and Path(path).is_file():
        return Path(path).read_bytes()
    raise FileNotFoundError(pet.get("photo_name", "fotografia"))


def delete_pet_photo_file(pet: dict[str, Any]) -> None:
    path = str(pet.get("photo_path", "") or "")
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass


def delete_pet_files(pet: dict[str, Any]) -> None:
    delete_pet_photo_file(pet)
    for doc in pet.get("documents", []):
        delete_document_file(doc)


def read_document_bytes(doc: dict[str, Any]) -> bytes:
    b64 = doc.get("data_b64", "")
    if b64:
        return base64.b64decode(b64)
    path = str(doc.get("storage_path", "") or "")
    if path and Path(path).is_file():
        return Path(path).read_bytes()
    raise FileNotFoundError(doc.get("name", "documento"))


def delete_document_file(doc: dict[str, Any]) -> None:
    path = str(doc.get("storage_path", "") or "")
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass


def materialize_attachments_to_files(state: dict[str, Any]) -> dict[str, Any]:
    for pet in state.get("pets", []):
        photo_b64 = pet.get("photo_b64", "")
        if photo_b64:
            try:
                photo_data = base64.b64decode(photo_b64)
                photo_name = pet.get("photo_name", "pet_photo.jpg") or "pet_photo.jpg"
                pet["photo_path"] = store_attachment_bytes(photo_data, photo_name)
                pet.pop("photo_b64", None)
            except Exception:
                pass
        for doc in pet.get("documents", []):
            b64 = doc.get("data_b64", "")
            if not b64:
                continue
            try:
                data = base64.b64decode(b64)
                doc["storage_path"] = store_attachment_bytes(data, doc.get("name", "documento.bin"))
                doc.pop("data_b64", None)
            except Exception:
                continue
    return state


# -----------------------------
# CSV / ZIP backup
# -----------------------------

def records_to_csv(records: list[dict[str, Any]]) -> bytes:
    keys: list[str] = []
    for r in records:
        for k, v in r.items():
            if k not in keys and not isinstance(v, (dict, list)):
                keys.append(k)
    if not keys:
        keys = ["id"]
    s = io.StringIO(newline="")
    writer = csv.DictWriter(s, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        writer.writerow({k: r.get(k, "") for k in keys})
    return s.getvalue().encode("utf-8-sig")


def make_backup_zip(state: dict[str, Any]) -> bytes:
    portable = deepcopy(state)
    # Populate attachment bytes in the portable JSON so restore works on another device.
    original_pets = {p.get("id"): p for p in state.get("pets", [])}
    for p in portable.get("pets", []):
        original = original_pets.get(p.get("id"), {})
        try:
            photo_data = read_pet_photo_bytes(original)
            p["photo_b64"] = base64.b64encode(photo_data).decode("ascii")
        except Exception:
            p["photo_b64"] = p.get("photo_b64", "") or ""
        p.pop("photo_path", None)
        original_docs = {d.get("id"): d for d in original.get("documents", [])}
        for doc in p.get("documents", []):
            source_doc = original_docs.get(doc.get("id"), doc)
            try:
                data = read_document_bytes(source_doc)
                doc["data_b64"] = base64.b64encode(data).decode("ascii")
            except Exception:
                doc["data_b64"] = ""
            doc.pop("storage_path", None)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pet_passport.json", json.dumps(portable, ensure_ascii=False, indent=2))
        for pet in portable.get("pets", []):
            pet_dir = safe_filename(pet.get("name", "animal"), "animal") + "_" + pet.get("id", "")[:8]
            for collection in (
                "vaccines", "medications", "appointments", "weights", "parasite_treatments",
                "allergies", "conditions", "surgeries", "exams", "travels", "reminders",
            ):
                zf.writestr(f"{pet_dir}/{collection}.csv", records_to_csv(pet.get(collection, [])))
            zf.writestr(f"{pet_dir}/report.pdf", make_pet_pdf(pet, portable.get("owner", {})))
            for doc in pet.get("documents", []):
                b64 = doc.get("data_b64", "")
                if not b64:
                    continue
                try:
                    data = base64.b64decode(b64)
                except Exception:
                    continue
                name = safe_filename(doc.get("name", "documento.bin"), "documento.bin")
                zf.writestr(f"{pet_dir}/documents/{doc.get('id', new_id())[:8]}_{name}", data)
    return buf.getvalue()


def restore_backup_bytes(data: bytes, filename: str = "") -> dict[str, Any]:
    lower = filename.lower()
    if lower.endswith(".zip") or data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            raw = zf.read("pet_passport.json")
            return ensure_state_shape(json.loads(raw.decode("utf-8")))
    return ensure_state_shape(json.loads(data.decode("utf-8")))


@dataclass
class RecordSection:
    key: str
    title: str
    icon: str
    fields: list[tuple[str, str, str]]
    primary: str
    secondary: str
    date_field: str = "date"


RECORD_SECTIONS: dict[str, RecordSection] = {
    "vaccines": RecordSection(
        "vaccines", "Vacinas", "vaccines",
        [
            ("name", "Nome da vacina", "text"), ("disease", "Doença", "text"),
            ("manufacturer", "Fabricante", "text"), ("lot", "Lote", "text"),
            ("date", "Data (AAAA-MM-DD)", "date"), ("valid_until", "Validade", "date"),
            ("next_due", "Próxima dose", "date"), ("veterinarian", "Veterinário", "text"),
            ("clinic", "Clínica", "text"), ("rabies", "Antirrábica (sim/não)", "bool"),
            ("notes", "Notas", "multiline"),
        ], "name", "disease"
    ),
    "medications": RecordSection(
        "medications", "Medicação", "medication",
        [
            ("name", "Medicamento", "text"), ("active_ingredient", "Princípio ativo", "text"),
            ("dose", "Dose", "text"), ("frequency", "Frequência", "text"),
            ("times", "Horários (ex.: 08:00, 20:00)", "text"),
            ("start_date", "Início", "date"), ("end_date", "Fim", "date"),
            ("veterinarian", "Veterinário", "text"), ("notes", "Notas", "multiline"),
        ], "name", "dose", "start_date"
    ),
    "appointments": RecordSection(
        "appointments", "Consultas", "event",
        [
            ("date", "Data", "date"), ("clinic", "Clínica", "text"),
            ("veterinarian", "Veterinário", "text"), ("reason", "Motivo", "text"),
            ("symptoms", "Sintomas", "multiline"), ("diagnosis", "Diagnóstico registado", "multiline"),
            ("treatment", "Tratamento", "multiline"), ("cost", "Valor pago", "text"),
            ("notes", "Notas", "multiline"),
        ], "reason", "clinic"
    ),
    "weights": RecordSection(
        "weights", "Peso", "monitor_weight",
        [("date", "Data", "date"), ("weight", "Peso (kg)", "number"), ("notes", "Notas", "multiline")],
        "weight", "notes"
    ),
    "parasite_treatments": RecordSection(
        "parasite_treatments", "Desparasitação", "bug_report",
        [
            ("category", "Categoria", "text"), ("product", "Produto", "text"),
            ("dose", "Dose", "text"), ("date", "Data", "date"),
            ("next_due", "Próxima aplicação", "date"), ("notes", "Notas", "multiline"),
        ], "product", "category"
    ),
    "allergies": RecordSection(
        "allergies", "Alergias", "warning",
        [
            ("name", "Alergia", "text"), ("type", "Tipo", "text"),
            ("reaction", "Reação conhecida", "multiline"), ("severity", "Gravidade", "text"),
            ("treatment", "Tratamento recomendado pelo veterinário", "multiline"),
            ("notes", "Notas", "multiline"),
        ], "name", "severity"
    ),
    "conditions": RecordSection(
        "conditions", "Condições médicas", "health_and_safety",
        [
            ("name", "Condição", "text"), ("date", "Data de identificação", "date"),
            ("veterinarian", "Veterinário", "text"), ("treatment", "Tratamento", "multiline"),
            ("notes", "Observações", "multiline"),
        ], "name", "treatment"
    ),
    "surgeries": RecordSection(
        "surgeries", "Cirurgias", "medical_services",
        [
            ("procedure", "Procedimento", "text"), ("date", "Data", "date"),
            ("clinic", "Clínica", "text"), ("veterinarian", "Veterinário", "text"),
            ("reason", "Motivo", "multiline"), ("recovery", "Recuperação", "multiline"),
            ("notes", "Notas", "multiline"),
        ], "procedure", "clinic"
    ),
    "exams": RecordSection(
        "exams", "Exames", "biotech",
        [
            ("type", "Tipo de exame", "text"), ("date", "Data", "date"),
            ("clinic", "Clínica", "text"), ("veterinarian", "Veterinário", "text"),
            ("result", "Resultado / resumo", "multiline"), ("notes", "Notas", "multiline"),
        ], "type", "result"
    ),
    "reminders": RecordSection(
        "reminders", "Lembretes", "notifications",
        [
            ("title", "Título", "text"), ("date", "Data", "date"),
            ("category", "Categoria", "text"), ("notes", "Notas", "multiline"),
        ], "title", "category"
    ),
}
