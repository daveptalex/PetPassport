from __future__ import annotations

import base64
import inspect
import io
import json
from datetime import datetime
from typing import Any, Callable

import flet as ft
import flet_local_auth as fla
import flet_secure_storage as fss

from core import (
    DATA_KEY,
    MAX_ATTACHMENT_BYTES,
    PIN_KEY,
    RECORD_SECTIONS,
    RecordSection,
    active_medications,
    age_text,
    build_timeline,
    default_state,
    delete_record,
    emergency_text,
    ensure_state_shape,
    find_pet,
    human_date,
    make_backup_zip,
    store_attachment_bytes,
    read_document_bytes,
    delete_document_file,
    read_pet_photo_bytes,
    delete_pet_photo_file,
    delete_pet_files,
    materialize_attachments_to_files,
    make_pet_pdf,
    make_pin_hash,
    make_qr_svg_bytes,
    make_record,
    new_id,
    normalize_date,
    now_iso,
    parse_date,
    records_to_csv,
    restore_backup_bytes,
    safe_filename,
    search_state,
    today_iso,
    touch,
    upcoming_events,
    upsert_record,
    verify_pin,
    empty_pet,
)

APP_NAME = "Pet Passport"
APP_VERSION = "1.0.0"
ACCENT = "#2F6F62"
ACCENT_DARK = "#1E4E45"
SOFT = "#EAF3F0"
DANGER = "#B42318"
WARNING = "#B54708"
WEB_WRAP_KEY = "UGV0UGFzc3BvcnQtV3JhcEtleS0yMDI2LVYxLTAxIg=="
WEB_WRAP_IV = "UGV0UGFzc3BvcnQtaXYtMDE="


def icon(name: str, fallback=ft.Icons.PETS):
    return getattr(ft.Icons, name.upper(), fallback)


def short(text: Any, n: int = 80) -> str:
    s = str(text or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


class PetPassportApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.state: dict[str, Any] = default_state()
        self.active_pet_id: str | None = None
        self.nav_index = 0
        self.storage = fss.SecureStorage(
            web_options=fss.WebOptions(
                db_name="PetPassportSecureStorage",
                public_key="PetPassport2026",
                wrap_key=WEB_WRAP_KEY,
                wrap_key_iv=WEB_WRAP_IV,
            )
        )
        self.local_auth = fla.LocalAuthentication()
        self.photo_picker = ft.FilePicker(on_result=self.on_photo_picked)
        self.document_picker = ft.FilePicker(on_result=self.on_document_picked)
        self.backup_picker = ft.FilePicker(on_result=self.on_backup_picked)
        self.page.services.extend([self.photo_picker, self.document_picker, self.backup_picker])
        self._configure_page()

    def _configure_page(self) -> None:
        self.page.title = APP_NAME
        self.page.padding = 0
        self.page.theme = ft.Theme(color_scheme_seed=ACCENT)
        self.page.dark_theme = ft.Theme(color_scheme_seed=ACCENT)
        self.page.theme_mode = ft.ThemeMode.SYSTEM
        self.page.navigation_bar = ft.NavigationBar(
            selected_index=0,
            on_change=self.on_nav_change,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.HOME_OUTLINED, selected_icon=ft.Icons.HOME, label="Início"),
                ft.NavigationBarDestination(icon=ft.Icons.BADGE_OUTLINED, selected_icon=ft.Icons.BADGE, label="Passport"),
                ft.NavigationBarDestination(icon=ft.Icons.HISTORY, selected_icon=ft.Icons.HISTORY_TOGGLE_OFF, label="Timeline"),
                ft.NavigationBarDestination(icon=ft.Icons.FOLDER_OUTLINED, selected_icon=ft.Icons.FOLDER, label="Documentos"),
                ft.NavigationBarDestination(icon=ft.Icons.MORE_HORIZ, label="Mais"),
            ],
        )

    async def start(self) -> None:
        await self.load_state()
        self.apply_theme()
        if self.state.get("pets"):
            self.active_pet_id = self.state["pets"][0].get("id")
        unlocked = await self.unlock_if_needed()
        if not unlocked:
            return
        self.render()
        if not self.state.get("settings", {}).get("medical_disclaimer_seen"):
            self.show_disclaimer()

    async def load_state(self) -> None:
        try:
            raw = await self.storage.get(key=DATA_KEY)
            if raw:
                self.state = ensure_state_shape(json.loads(raw))
            else:
                self.state = default_state()
        except Exception:
            self.state = default_state()

    async def save_state(self) -> None:
        self.state["updated_at"] = now_iso()
        payload = json.dumps(self.state, ensure_ascii=False, separators=(",", ":"))
        await self.storage.set(key=DATA_KEY, value=payload)

    def apply_theme(self) -> None:
        mode = self.state.get("settings", {}).get("theme", "system")
        self.page.theme_mode = {
            "light": ft.ThemeMode.LIGHT,
            "dark": ft.ThemeMode.DARK,
        }.get(mode, ft.ThemeMode.SYSTEM)

    async def unlock_if_needed(self) -> bool:
        pin_hash = ""
        try:
            pin_hash = await self.storage.get(key=PIN_KEY) or ""
        except Exception:
            pass
        bio_enabled = bool(self.state.get("settings", {}).get("biometric_enabled"))
        if bio_enabled and not self.page.web:
            try:
                ok = await self.local_auth.authenticate(
                    "Desbloquear o Pet Passport",
                    biometric_only=False,
                    sensitive_transaction=True,
                )
                if ok:
                    return True
            except Exception:
                pass
        if pin_hash:
            self.show_unlock_dialog(pin_hash)
            return False
        return True

    def show_unlock_dialog(self, pin_hash: str) -> None:
        pin = ft.TextField(label="PIN", password=True, can_reveal_password=True, keyboard_type=ft.KeyboardType.NUMBER)
        error = ft.Text("", color=DANGER)

        async def unlock(_):
            if verify_pin(pin.value or "", pin_hash):
                self.page.pop_dialog()
                self.render()
                if not self.state.get("settings", {}).get("medical_disclaimer_seen"):
                    self.show_disclaimer()
            else:
                error.value = "PIN incorreto."
                self.page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Pet Passport bloqueado"),
            content=ft.Column([ft.Text("Introduza o PIN para continuar."), pin, error], tight=True),
            actions=[ft.FilledButton(content="Desbloquear", icon=ft.Icons.LOCK_OPEN, on_click=unlock)],
        )
        self.page.show_dialog(dlg)

    def show_disclaimer(self) -> None:
        async def accept(_):
            self.state["settings"]["medical_disclaimer_seen"] = True
            await self.save_state()
            self.page.pop_dialog()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Informação veterinária"),
            content=ft.Text(
                "O Pet Passport organiza informação fornecida pelo tutor e pelos profissionais de saúde animal. "
                "Não realiza diagnósticos e não substitui aconselhamento veterinário."
            ),
            actions=[ft.FilledButton(content="Compreendi", on_click=accept)],
        )
        self.page.show_dialog(dlg)

    def current_pet(self) -> dict[str, Any] | None:
        pet = find_pet(self.state, self.active_pet_id)
        if pet:
            return pet
        pets = self.state.get("pets", [])
        if pets:
            self.active_pet_id = pets[0].get("id")
            return pets[0]
        return None

    def on_nav_change(self, e) -> None:
        self.nav_index = int(e.control.selected_index or 0)
        self.render()

    def render(self) -> None:
        self.page.controls.clear()
        if self.page.navigation_bar:
            self.page.navigation_bar.selected_index = self.nav_index
        builders = [self.home_view, self.passport_view, self.timeline_view, self.documents_view, self.more_view]
        body = builders[self.nav_index]()
        self.page.add(
            ft.SafeArea(
                expand=True,
                content=ft.Container(
                    padding=ft.Padding.only(left=14, right=14, top=12, bottom=8),
                    content=body,
                ),
            )
        )
        self.page.update()

    # -----------------------------
    # Common UI
    # -----------------------------
    def header(self, title: str, subtitle: str = "", trailing: ft.Control | None = None) -> ft.Control:
        controls: list[ft.Control] = [
            ft.Column(
                [
                    ft.Text(title, size=28, weight=ft.FontWeight.BOLD),
                    ft.Text(subtitle, size=13, opacity=0.7) if subtitle else ft.Container(),
                ],
                spacing=2,
                expand=True,
            )
        ]
        if trailing:
            controls.append(trailing)
        return ft.Row(controls=controls, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def panel(self, content: ft.Control, padding: int = 16, bgcolor: str | None = None) -> ft.Container:
        return ft.Container(
            content=content,
            padding=padding,
            bgcolor=bgcolor or SOFT,
            border_radius=18,
        )

    def empty_message(self, title: str, subtitle: str, button_text: str | None = None, on_click=None) -> ft.Control:
        controls: list[ft.Control] = [
            ft.Icon(ft.Icons.PETS, size=52, color=ACCENT),
            ft.Text(title, size=22, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ft.Text(subtitle, text_align=ft.TextAlign.CENTER, opacity=0.7),
        ]
        if button_text and on_click:
            controls.append(ft.FilledButton(content=button_text, icon=ft.Icons.ADD, on_click=on_click))
        return ft.Container(
            expand=True,
            alignment=ft.Alignment.CENTER,
            content=ft.Column(controls, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
        )

    def pet_selector(self) -> ft.Control:
        pets = self.state.get("pets", [])
        if not pets:
            return ft.Container()

        def change(e):
            self.active_pet_id = e.control.value
            self.render()

        return ft.Dropdown(
            label="Animal",
            value=self.active_pet_id or pets[0].get("id"),
            options=[ft.DropdownOption(key=p.get("id", ""), text=p.get("name", "Animal")) for p in pets],
            on_select=change,
            width=220,
        )

    async def open_form(
        self,
        title: str,
        fields: list[tuple[str, str, str]],
        initial: dict[str, Any] | None,
        on_save: Callable[[dict[str, Any]], Any],
        save_label: str = "Guardar",
    ) -> None:
        initial = dict(initial or {})
        controls: dict[str, Any] = {}
        rows: list[ft.Control] = []
        for key, label, kind in fields:
            value = initial.get(key, "")
            if kind == "bool":
                ctrl = ft.Dropdown(
                    label=label,
                    value="sim" if bool(value) else "nao",
                    options=[ft.DropdownOption(key="sim", text="Sim"), ft.DropdownOption(key="nao", text="Não")],
                )
            else:
                ctrl = ft.TextField(
                    label=label,
                    value=str(value or ""),
                    multiline=kind == "multiline",
                    min_lines=2 if kind == "multiline" else 1,
                    max_lines=5 if kind == "multiline" else 1,
                    keyboard_type=ft.KeyboardType.NUMBER if kind == "number" else ft.KeyboardType.TEXT,
                    hint_text="AAAA-MM-DD" if kind == "date" else None,
                )
            controls[key] = (ctrl, kind)
            rows.append(ctrl)

        error = ft.Text("", color=DANGER)

        async def save(_):
            result = dict(initial)
            for key, (ctrl, kind) in controls.items():
                if kind == "bool":
                    result[key] = ctrl.value == "sim"
                else:
                    val = (ctrl.value or "").strip()
                    result[key] = normalize_date(val) if kind == "date" else val
            first_key = fields[0][0] if fields else ""
            if first_key and not str(result.get(first_key, "")).strip():
                error.value = f"O campo “{fields[0][1]}” é obrigatório."
                self.page.update()
                return
            self.page.pop_dialog()
            ret = on_save(result)
            if inspect.isawaitable(ret):
                await ret

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Container(
                width=560,
                height=500,
                content=ft.Column(rows + [error], scroll=ft.ScrollMode.AUTO, spacing=10),
            ),
            actions=[
                ft.TextButton(content="Cancelar", on_click=lambda _: self.page.pop_dialog()),
                ft.FilledButton(content=save_label, icon=ft.Icons.SAVE, on_click=save),
            ],
        )
        self.page.show_dialog(dlg)

    def confirm(self, title: str, message: str, action: Callable[[], Any], danger: bool = False) -> None:
        async def yes(_):
            self.page.pop_dialog()
            ret = action()
            if inspect.isawaitable(ret):
                await ret

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[
                ft.TextButton(content="Cancelar", on_click=lambda _: self.page.pop_dialog()),
                ft.FilledButton(content="Confirmar", on_click=yes, bgcolor=DANGER if danger else ACCENT, color="#FFFFFF"),
            ],
        )
        self.page.show_dialog(dlg)

    def snack(self, message: str) -> None:
        self.page.show_dialog(ft.SnackBar(content=ft.Text(message)))

    # -----------------------------
    # Home
    # -----------------------------
    def home_view(self) -> ft.Control:
        pets = self.state.get("pets", [])
        add_btn = ft.FilledButton(content="Adicionar animal", icon=ft.Icons.ADD, on_click=self.add_pet)
        if not pets:
            return ft.Column(
                [
                    self.header("Pet Passport", "Tudo o que é importante sobre o seu animal. Num só lugar seguro."),
                    self.empty_message(
                        "Ainda não existem animais",
                        "Comece por criar o primeiro perfil. Só precisa do nome e da espécie; o restante pode ser preenchido depois.",
                        "Adicionar primeiro animal",
                        self.add_pet,
                    ),
                ],
                expand=True,
            )

        cards = [self.pet_card(p) for p in pets]
        pet = self.current_pet()
        upcoming = upcoming_events(pet, 120)[:6] if pet else []
        meds = active_medications(pet) if pet else []

        event_controls: list[ft.Control] = []
        if upcoming:
            for ev in upcoming:
                event_controls.append(
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.EVENT, color=ACCENT),
                        title=ft.Text(ev["title"]),
                        subtitle=ft.Text(f"{human_date(ev['date'])} · {ev['subtitle']}"),
                    )
                )
        else:
            event_controls.append(ft.Text("Sem eventos previstos nos próximos 120 dias.", opacity=0.7))

        med_controls: list[ft.Control] = []
        if meds:
            for med in meds[:5]:
                med_controls.append(self.medication_today_row(pet, med))
        else:
            med_controls.append(ft.Text("Sem medicação ativa registada.", opacity=0.7))

        return ft.Column(
            [
                self.header("Pet Passport", "Arquivo pessoal e passaporte digital", add_btn),
                ft.TextField(
                    label="Pesquisa rápida",
                    hint_text="Ex.: vacina, microchip, amoxicilina…",
                    prefix_icon=ft.Icons.SEARCH,
                    on_submit=lambda e: self.show_search_results(e.control.value or ""),
                ),
                ft.Text("Meus animais", size=18, weight=ft.FontWeight.BOLD),
                ft.ResponsiveRow(controls=cards, run_spacing=10, spacing=10),
                ft.Row([ft.Text("Próximos eventos", size=18, weight=ft.FontWeight.BOLD), self.pet_selector()], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self.panel(ft.Column(event_controls, spacing=2)),
                ft.Text("Medicação atual", size=18, weight=ft.FontWeight.BOLD),
                self.panel(ft.Column(med_controls, spacing=6), bgcolor="#F7F6EE"),
                ft.Container(height=18),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=12,
        )

    def pet_card(self, pet: dict[str, Any]) -> ft.Control:
        next_events = upcoming_events(pet, 365)
        next_text = "Sem eventos próximos"
        if next_events:
            next_text = f"{next_events[0]['kind']}: {human_date(next_events[0]['date'])}"
        initial = (pet.get("name") or "?")[:1].upper()
        return ft.Container(
            col={"xs": 12, "sm": 6, "md": 4},
            padding=16,
            bgcolor="#F6FAF8",
            border_radius=18,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.CircleAvatar(content=ft.Text(initial, size=22, weight=ft.FontWeight.BOLD), bgcolor=SOFT, color=ACCENT_DARK),
                            ft.Column(
                                [
                                    ft.Text(pet.get("name", "Animal"), size=20, weight=ft.FontWeight.BOLD),
                                    ft.Text(f"{pet.get('species', '')} · {pet.get('breed', '') or 'Raça não indicada'}", opacity=0.7),
                                ], spacing=2, expand=True,
                            ),
                        ]
                    ),
                    ft.Text(f"{age_text(pet.get('birth_date', ''))} · Microchip: {pet.get('microchip', {}).get('number', '') or 'não registado'}", size=12),
                    ft.Text(next_text, size=12, color=ACCENT_DARK),
                    ft.Row(
                        [
                            ft.FilledButton(content="Abrir Passport", icon=ft.Icons.BADGE, on_click=lambda _, p=pet: self.open_pet(p)),
                            ft.IconButton(icon=ft.Icons.MORE_VERT, tooltip="Perfil", on_click=lambda _, p=pet: self.open_pet_profile(p)),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ], spacing=10,
            ),
        )

    def open_pet(self, pet: dict[str, Any]) -> None:
        self.active_pet_id = pet.get("id")
        self.nav_index = 1
        self.render()

    def open_pet_profile(self, pet: dict[str, Any]) -> None:
        self.active_pet_id = pet.get("id")
        self.show_profile_sheet()

    def medication_today_row(self, pet: dict[str, Any], med: dict[str, Any]) -> ft.Control:
        times = med.get("times", "") or med.get("frequency", "")

        async def taken(_):
            med.setdefault("dose_log", []).append({"timestamp": now_iso(), "status": "taken"})
            touch(med)
            touch(pet)
            await self.save_state()
            self.snack(f"Dose de {med.get('name', 'medicação')} registada.")
            self.render()

        return ft.Row(
            [
                ft.Icon(ft.Icons.MEDICATION, color=ACCENT),
                ft.Column([ft.Text(med.get("name", "Medicamento"), weight=ft.FontWeight.BOLD), ft.Text(f"{med.get('dose', '')} · {times}", size=12, opacity=0.7)], expand=True, spacing=1),
                ft.OutlinedButton(content="Tomado", icon=ft.Icons.CHECK, on_click=taken),
            ]
        )

    # -----------------------------
    # Pet profile / passport
    # -----------------------------
    async def add_pet(self, _=None) -> None:
        fields = [
            ("name", "Nome", "text"),
            ("species", "Espécie", "text"),
            ("birth_date", "Data de nascimento", "date"),
            ("breed", "Raça", "text"),
        ]

        async def save(values):
            pet = empty_pet()
            pet.update(values)
            self.state["pets"].append(pet)
            self.active_pet_id = pet["id"]
            await self.save_state()
            self.nav_index = 1
            self.render()

        await self.open_form("Adicionar animal", fields, {"species": "Cão"}, save, "Criar perfil")

    def passport_view(self) -> ft.Control:
        pet = self.current_pet()
        if not pet:
            return self.empty_message("Sem animal selecionado", "Adicione um animal para criar o passaporte digital.", "Adicionar animal", self.add_pet)

        vaccine_status = self.vaccine_status(pet)
        photo_control: ft.Control
        if pet.get("photo_b64") or pet.get("photo_path"):
            try:
                photo_control = ft.Image(src=read_pet_photo_bytes(pet), width=120, height=120, fit=ft.BoxFit.COVER, border_radius=60)
            except Exception:
                photo_control = ft.CircleAvatar(content=ft.Text((pet.get("name") or "?")[:1]), radius=50)
        else:
            photo_control = ft.CircleAvatar(content=ft.Icon(ft.Icons.PETS, size=42), radius=50, bgcolor=SOFT)

        passport = ft.Container(
            padding=18,
            border_radius=22,
            bgcolor=ACCENT_DARK,
            content=ft.Column(
                [
                    ft.Row([ft.Text("PET PASSPORT", size=22, weight=ft.FontWeight.BOLD), ft.Icon(ft.Icons.PETS, color="#FFFFFF")], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Divider(color="#80FFFFFF"),
                    ft.Row(
                        [
                            photo_control,
                            ft.Column(
                                [
                                    ft.Text(pet.get("name", ""), size=26, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                                    ft.Text(f"{pet.get('species', '')} · {pet.get('breed', '')}", color="#FFFFFF"),
                                    ft.Text(f"Sexo: {pet.get('sex', '') or '—'}", color="#FFFFFF"),
                                    ft.Text(f"Nascimento: {human_date(pet.get('birth_date'))}", color="#FFFFFF"),
                                    ft.Text(f"Microchip: {pet.get('microchip', {}).get('number', '') or '—'}", color="#FFFFFF"),
                                ], spacing=4, expand=True,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    ft.Row(
                        [
                            ft.Text(f"Vacinas: {vaccine_status}", color="#FFFFFF"),
                            ft.Text(f"Peso: {pet.get('current_weight', '') or '—'} kg", color="#FFFFFF"),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ], spacing=10,
            ),
        )

        quick = ft.ResponsiveRow(
            controls=[
                self.quick_tile("Saúde", ft.Icons.HEALTH_AND_SAFETY, lambda _: self.show_health_menu()),
                self.quick_tile("Vacinas", ft.Icons.VACCINES, lambda _: self.open_record_section("vaccines")),
                self.quick_tile("Medicação", ft.Icons.MEDICATION, lambda _: self.open_record_section("medications")),
                self.quick_tile("Viagens", ft.Icons.FLIGHT, lambda _: self.open_travel_view()),
                self.quick_tile("QR", ft.Icons.QR_CODE_2, lambda _: self.show_qr()),
                self.quick_tile("Emergência", ft.Icons.EMERGENCY, lambda _: self.show_emergency()),
            ], spacing=8, run_spacing=8,
        )

        profile_actions = ft.Row(
            controls=[
                ft.OutlinedButton(content="Editar perfil", icon=ft.Icons.EDIT, on_click=lambda _: self.edit_pet()),
                ft.OutlinedButton(
                    content="Fotografia",
                    icon=ft.Icons.PHOTO_CAMERA,
                    action=ft.PickFiles(
                        self.photo_picker,
                        allow_multiple=False,
                        with_data=True,
                        compression_quality=75,
                        cancel_upload_on_window_blur=False,
                    ),
                ),
                ft.OutlinedButton(content="Microchip", icon=ft.Icons.MEMORY, on_click=lambda _: self.edit_microchip()),
                ft.OutlinedButton(content="Veterinário", icon=ft.Icons.LOCAL_HOSPITAL, on_click=lambda _: self.edit_veterinary()),
                ft.OutlinedButton(content="Seguro", icon=ft.Icons.SHIELD_OUTLINED, on_click=lambda _: self.edit_insurance()),
                ft.OutlinedButton(content="Animal perdido", icon=ft.Icons.CAMPAIGN, on_click=lambda _: self.edit_lost_mode()),
                ft.OutlinedButton(content="Relatório PDF", icon=ft.Icons.PICTURE_AS_PDF, on_click=lambda _: self.export_pet_pdf()),
                ft.OutlinedButton(content="Eliminar animal", icon=ft.Icons.DELETE_FOREVER, on_click=lambda _: self.delete_current_pet()),
            ], wrap=True, spacing=8, run_spacing=8,
        )

        return ft.Column(
            [
                self.header("Passaporte digital", "Identificação, saúde e documentos", self.pet_selector()),
                passport,
                quick,
                ft.Text("Gestão do perfil", size=18, weight=ft.FontWeight.BOLD),
                profile_actions,
                ft.Text("Resumo", size=18, weight=ft.FontWeight.BOLD),
                self.profile_summary(pet),
                ft.Container(height=18),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=12,
        )

    def quick_tile(self, label: str, ico, on_click) -> ft.Control:
        return ft.Container(
            col={"xs": 6, "sm": 4, "md": 2},
            content=ft.Button(
                content=ft.Column([ft.Icon(ico, size=28), ft.Text(label, text_align=ft.TextAlign.CENTER)], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
                on_click=on_click,
                height=84,
            ),
        )

    def vaccine_status(self, pet: dict[str, Any]) -> str:
        if not pet.get("vaccines"):
            return "sem registos"
        today = datetime.now().date()
        expired = 0
        soon = 0
        for v in pet.get("vaccines", []):
            d = parse_date(v.get("valid_until") or v.get("next_due"))
            if d and d < today:
                expired += 1
            elif d and (d - today).days <= 30:
                soon += 1
        if expired:
            return f"{expired} expirada(s)"
        if soon:
            return f"{soon} próxima(s) do prazo"
        return "atualizadas"

    def profile_summary(self, pet: dict[str, Any]) -> ft.Control:
        allergies = ", ".join(a.get("name", "") for a in pet.get("allergies", []) if a.get("name")) or "Nenhuma registada"
        conditions = ", ".join(c.get("name", "") for c in pet.get("conditions", []) if c.get("name")) or "Nenhuma registada"
        return self.panel(
            ft.Column(
                [
                    ft.Text(f"Identificação: {pet.get('species', '')} · {pet.get('breed', '') or 'raça não indicada'} · {pet.get('sex', '') or 'sexo não indicado'}"),
                    ft.Text(f"Idade: {age_text(pet.get('birth_date', ''))}"),
                    ft.Text(f"Microchip: {pet.get('microchip', {}).get('number', '') or 'não registado'}"),
                    ft.Text(f"Alergias: {allergies}", color=DANGER if pet.get("allergies") else None),
                    ft.Text(f"Condições: {conditions}"),
                    ft.Text(f"Clínica: {pet.get('veterinary', {}).get('clinic', '') or 'não indicada'}"),
                    ft.Text("Este resumo é administrativo e não constitui aconselhamento veterinário.", size=11, opacity=0.6),
                ], spacing=6,
            )
        )

    async def edit_pet(self) -> None:
        pet = self.current_pet()
        if not pet:
            return
        fields = [
            ("name", "Nome", "text"), ("species", "Espécie", "text"), ("breed", "Raça", "text"),
            ("secondary_breed", "Raça secundária / cruzamento", "text"), ("sex", "Sexo", "text"),
            ("birth_date", "Data de nascimento", "date"), ("color", "Cor", "text"), ("coat", "Pelagem", "text"),
            ("current_weight", "Peso atual (kg)", "number"), ("reproductive_status", "Estado reprodutivo", "text"),
            ("neutered", "Esterilizado/castrado", "bool"), ("distinctive_features", "Características distintivas", "multiline"),
        ]

        async def save(values):
            pet.update(values)
            touch(pet)
            await self.save_state()
            self.render()

        await self.open_form("Editar perfil do animal", fields, pet, save)

    async def edit_microchip(self) -> None:
        pet = self.current_pet()
        if not pet:
            return
        fields = [
            ("number", "Número do microchip", "text"), ("implant_date", "Data de implantação", "date"),
            ("implant_location", "Local de implantação", "text"), ("country", "País", "text"),
            ("registry", "Entidade registadora", "text"), ("veterinarian", "Veterinário", "text"),
        ]

        async def save(values):
            pet["microchip"] = values
            touch(pet)
            await self.save_state()
            self.render()

        await self.open_form("Microchip", fields, pet.get("microchip", {}), save)

    async def edit_veterinary(self) -> None:
        pet = self.current_pet()
        if not pet:
            return
        fields = [
            ("clinic", "Clínica", "text"), ("veterinarian", "Veterinário", "text"),
            ("address", "Morada", "multiline"), ("phone", "Telefone", "text"), ("email", "Email", "text"),
            ("website", "Website", "text"), ("hours", "Horário", "text"), ("emergency_phone", "Telefone de emergência", "text"),
        ]

        async def save(values):
            pet["veterinary"] = values
            touch(pet)
            await self.save_state()
            self.render()

        await self.open_form("Veterinário / clínica", fields, pet.get("veterinary", {}), save)

    async def edit_insurance(self) -> None:
        pet = self.current_pet()
        if not pet:
            return
        fields = [
            ("company", "Seguradora", "text"), ("policy", "Número da apólice", "text"),
            ("coverage", "Cobertura", "multiline"), ("start_date", "Data de início", "date"),
            ("renewal_date", "Data de renovação", "date"), ("contact", "Contacto", "text"),
            ("deductible", "Franquia", "text"), ("notes", "Notas", "multiline"),
        ]

        async def save(values):
            pet["insurance"] = values
            touch(pet)
            await self.save_state()
            self.render()

        await self.open_form("Seguro", fields, pet.get("insurance", {}), save)

    async def edit_lost_mode(self) -> None:
        pet = self.current_pet()
        if not pet:
            return
        fields = [
            ("active", "Modo animal perdido ativo", "bool"), ("public_phone", "Telefone público", "text"),
            ("message", "Mensagem pública", "multiline"), ("last_seen_place", "Último local conhecido", "text"),
            ("last_seen_date", "Data em que foi visto pela última vez", "date"),
        ]

        async def save(values):
            pet["lost_mode"] = values
            touch(pet)
            await self.save_state()
            self.render()

        await self.open_form("Modo animal perdido", fields, pet.get("lost_mode", {}), save)

    async def on_photo_picked(self, e) -> None:
        pet = self.current_pet()
        if not pet:
            return
        files = list(e.files or [])
        if not files:
            return
        f = files[0]
        if not f.bytes:
            self.snack("Não foi possível ler a imagem selecionada.")
            return
        if len(f.bytes) > MAX_ATTACHMENT_BYTES:
            self.snack("A imagem é demasiado grande. Limite: 5 MB.")
            return
        delete_pet_photo_file(pet)
        pet["photo_name"] = f.name
        if self.page.web:
            pet["photo_b64"] = base64.b64encode(f.bytes).decode("ascii")
            pet["photo_path"] = ""
        else:
            pet["photo_path"] = store_attachment_bytes(f.bytes, f.name)
            pet["photo_b64"] = ""
        touch(pet)
        await self.save_state()
        self.render()

    def show_profile_sheet(self) -> None:
        pet = self.current_pet()
        if not pet:
            return
        dlg = ft.AlertDialog(
            title=ft.Text(pet.get("name", "Animal")),
            content=ft.Column(
                [
                    ft.Text(f"{pet.get('species', '')} · {pet.get('breed', '')}"),
                    ft.Text(f"Nascimento: {human_date(pet.get('birth_date'))}"),
                    ft.Text(f"Microchip: {pet.get('microchip', {}).get('number', '') or '—'}"),
                    ft.Text(f"Peso: {pet.get('current_weight', '') or '—'} kg"),
                ], tight=True,
            ),
            actions=[
                ft.TextButton(content="Fechar", on_click=lambda _: self.page.pop_dialog()),
                ft.FilledButton(content="Abrir Passport", on_click=lambda _: (self.page.pop_dialog(), self.open_pet(pet))),
            ],
        )
        self.page.show_dialog(dlg)

    # -----------------------------
    # Health and generic sections
    # -----------------------------
    def show_health_menu(self) -> None:
        items = [
            ("Consultas", "appointments", ft.Icons.EVENT),
            ("Peso", "weights", ft.Icons.MONITOR_WEIGHT),
            ("Desparasitação", "parasite_treatments", ft.Icons.BUG_REPORT),
            ("Alergias", "allergies", ft.Icons.WARNING_AMBER),
            ("Condições médicas", "conditions", ft.Icons.HEALTH_AND_SAFETY),
            ("Cirurgias", "surgeries", ft.Icons.MEDICAL_SERVICES),
            ("Exames", "exams", ft.Icons.BIOTECH),
            ("Lembretes", "reminders", ft.Icons.NOTIFICATIONS),
        ]
        dlg = ft.AlertDialog(
            title=ft.Text("Saúde"),
            content=ft.Container(
                width=480,
                content=ft.Column(
                    [ft.ListTile(leading=ft.Icon(ic), title=ft.Text(label), on_click=lambda _, k=key: (self.page.pop_dialog(), self.open_record_section(k))) for label, key, ic in items],
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[ft.TextButton(content="Fechar", on_click=lambda _: self.page.pop_dialog())],
        )
        self.page.show_dialog(dlg)

    def open_record_section(self, key: str) -> None:
        sec = RECORD_SECTIONS[key]
        pet = self.current_pet()
        if not pet:
            return
        records = list(pet.get(key, []))
        date_field = sec.date_field
        records.sort(key=lambda r: str(r.get(date_field, r.get("created_at", ""))), reverse=True)

        async def add(_=None):
            self.page.pop_dialog()
            await self.edit_record(sec, None)

        async def export_csv(_=None):
            data = records_to_csv(pet.get(key, []))
            await ft.FilePicker().save_file(
                file_name=f"{safe_filename(pet.get('name', 'animal'))}_{key}.csv",
                allowed_extensions=["csv"],
                file_type=ft.FilePickerFileType.CUSTOM,
                src_bytes=data,
            )

        cards: list[ft.Control] = []
        for rec in records:
            title = str(rec.get(sec.primary, "") or sec.title)
            sub = str(rec.get(sec.secondary, "") or "")
            date_value = rec.get(date_field, "")
            trailing_buttons = [
                ft.IconButton(icon=ft.Icons.EDIT, tooltip="Editar", on_click=lambda _, r=rec: self.page.run_task(self.edit_record, sec, r)),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="Eliminar", icon_color=DANGER, on_click=lambda _, r=rec: self.delete_generic_record(sec, r)),
            ]
            if key == "medications":
                trailing_buttons.insert(0, ft.IconButton(icon=ft.Icons.CHECK_CIRCLE_OUTLINE, tooltip="Registar dose tomada", on_click=lambda _, r=rec: self.page.run_task(self.mark_med_taken, r)))
            cards.append(
                self.panel(
                    ft.Row(
                        [
                            ft.Icon(icon(sec.icon, ft.Icons.LIST), color=ACCENT),
                            ft.Column(
                                [
                                    ft.Text(title, weight=ft.FontWeight.BOLD),
                                    ft.Text(short(sub, 110), size=12, opacity=0.7) if sub else ft.Container(),
                                    ft.Text(human_date(date_value), size=11, opacity=0.6) if date_value else ft.Container(),
                                ], expand=True, spacing=2,
                            ),
                            ft.Row(trailing_buttons, spacing=0),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ), bgcolor="#F7FAF9"
                )
            )
        if not cards:
            cards = [ft.Text("Ainda não existem registos nesta secção.", opacity=0.7)]

        dlg = ft.AlertDialog(
            title=ft.Text(f"{sec.title} · {pet.get('name', '')}"),
            content=ft.Container(width=680, height=540, content=ft.Column(cards, scroll=ft.ScrollMode.AUTO, spacing=8)),
            actions=[
                ft.TextButton(content="Fechar", on_click=lambda _: self.page.pop_dialog()),
                ft.OutlinedButton(content="CSV", icon=ft.Icons.DOWNLOAD, on_click=export_csv),
                ft.FilledButton(content="Adicionar", icon=ft.Icons.ADD, on_click=add),
            ],
        )
        self.page.show_dialog(dlg)

    async def edit_record(self, sec: RecordSection, record: dict[str, Any] | None) -> None:
        pet = self.current_pet()
        if not pet:
            return
        initial = dict(record or {})
        if not record:
            if any(f[0] == "date" for f in sec.fields):
                initial["date"] = today_iso()
            if any(f[0] == "start_date" for f in sec.fields):
                initial["start_date"] = today_iso()

        async def save(values):
            if record:
                values["id"] = record.get("id")
                values["created_at"] = record.get("created_at", now_iso())
                if "dose_log" in record:
                    values["dose_log"] = record.get("dose_log", [])
            else:
                values = make_record(**values)
            upsert_record(pet, sec.key, values)
            if sec.key == "weights" and values.get("weight"):
                pet["current_weight"] = values.get("weight")
            await self.save_state()
            self.page.pop_dialog() if False else None
            self.open_record_section(sec.key)
            self.render()

        if record:
            self.page.pop_dialog()
        await self.open_form(f"{'Editar' if record else 'Adicionar'} — {sec.title}", sec.fields, initial, save)

    def delete_generic_record(self, sec: RecordSection, record: dict[str, Any]) -> None:
        pet = self.current_pet()
        if not pet:
            return

        async def do_delete():
            delete_record(pet, sec.key, record.get("id", ""))
            await self.save_state()
            self.open_record_section(sec.key)
            self.render()

        self.page.pop_dialog()
        self.confirm("Eliminar registo", "Esta operação não pode ser anulada. Pretende continuar?", do_delete, danger=True)

    async def mark_med_taken(self, med: dict[str, Any]) -> None:
        pet = self.current_pet()
        if not pet:
            return
        med.setdefault("dose_log", []).append({"timestamp": now_iso(), "status": "taken"})
        touch(med)
        touch(pet)
        await self.save_state()
        self.snack("Dose registada como tomada.")

    # -----------------------------
    # Travel
    # -----------------------------
    def open_travel_view(self) -> None:
        pet = self.current_pet()
        if not pet:
            return
        cards: list[ft.Control] = []
        for travel in sorted(pet.get("travels", []), key=lambda x: x.get("departure", ""), reverse=True):
            checklist = travel.get("checklist", {})
            done = sum(1 for v in checklist.values() if v)
            total = len(checklist) or 6
            cards.append(
                self.panel(
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.FLIGHT, color=ACCENT),
                            ft.Column(
                                [
                                    ft.Text(travel.get("destination", "Viagem"), weight=ft.FontWeight.BOLD),
                                    ft.Text(f"{travel.get('country', '')} · {human_date(travel.get('departure'))} → {human_date(travel.get('return'))}"),
                                    ft.Text(f"Checklist: {done}/{total}", size=12, opacity=0.7),
                                ], expand=True,
                            ),
                            ft.IconButton(icon=ft.Icons.EDIT, on_click=lambda _, t=travel: self.page.run_task(self.edit_travel, t)),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=DANGER, on_click=lambda _, t=travel: self.delete_travel(t)),
                        ]
                    ), bgcolor="#F7FAF9"
                )
            )
        if not cards:
            cards = [ft.Text("Ainda não existem viagens registadas.", opacity=0.7)]
        dlg = ft.AlertDialog(
            title=ft.Text(f"Viagens · {pet.get('name', '')}"),
            content=ft.Container(width=650, height=500, content=ft.Column(cards, scroll=ft.ScrollMode.AUTO, spacing=8)),
            actions=[
                ft.TextButton(content="Fechar", on_click=lambda _: self.page.pop_dialog()),
                ft.FilledButton(content="Adicionar viagem", icon=ft.Icons.ADD, on_click=self.add_travel_from_dialog),
            ],
        )
        self.page.show_dialog(dlg)


    def add_travel_from_dialog(self, _=None) -> None:
        self.page.pop_dialog()
        self.page.run_task(self.edit_travel, None)

    async def edit_travel(self, travel: dict[str, Any] | None) -> None:
        pet = self.current_pet()
        if not pet:
            return
        if travel:
            self.page.pop_dialog()
        fields = [
            ("destination", "Destino", "text"), ("country", "País", "text"),
            ("departure", "Partida", "date"), ("return", "Regresso", "date"),
            ("transport", "Transporte", "text"), ("accommodation", "Alojamento", "text"),
            ("notes", "Notas", "multiline"),
        ]

        async def save(values):
            checklist = dict((travel or {}).get("checklist", {})) or {
                "microchip": False, "rabies": False, "passport": False,
                "vet_certificate": False, "medication": False, "carrier": False,
            }
            if travel:
                values.update({"id": travel.get("id"), "created_at": travel.get("created_at", now_iso())})
            else:
                values = make_record(**values)
            values["checklist"] = checklist
            upsert_record(pet, "travels", values)
            await self.save_state()
            self.show_travel_checklist(values)

        await self.open_form("Viagem", fields, travel or {"departure": today_iso()}, save)

    def show_travel_checklist(self, travel: dict[str, Any]) -> None:
        pet = self.current_pet()
        if not pet:
            return
        labels = {
            "microchip": "Microchip",
            "rabies": "Vacina antirrábica",
            "passport": "Passaporte",
            "vet_certificate": "Certificado veterinário",
            "medication": "Medicação",
            "carrier": "Transportadora",
        }
        switches: dict[str, ft.Checkbox] = {}
        for key, label in labels.items():
            switches[key] = ft.Checkbox(label=label, value=bool(travel.setdefault("checklist", {}).get(key)))

        async def save(_):
            for key, sw in switches.items():
                travel["checklist"][key] = bool(sw.value)
            touch(travel)
            touch(pet)
            await self.save_state()
            self.page.pop_dialog()
            self.snack("Checklist de viagem guardada.")

        dlg = ft.AlertDialog(
            title=ft.Text(f"Checklist — {travel.get('destination', '')}"),
            content=ft.Column(list(switches.values()), tight=True),
            actions=[ft.FilledButton(content="Guardar checklist", icon=ft.Icons.CHECKLIST, on_click=save)],
        )
        self.page.show_dialog(dlg)

    def delete_travel(self, travel: dict[str, Any]) -> None:
        pet = self.current_pet()
        if not pet:
            return

        async def do_delete():
            delete_record(pet, "travels", travel.get("id", ""))
            await self.save_state()
            self.open_travel_view()
            self.render()

        self.page.pop_dialog()
        self.confirm("Eliminar viagem", "Eliminar este registo de viagem?", do_delete, danger=True)

    # -----------------------------
    # Timeline
    # -----------------------------
    def timeline_view(self) -> ft.Control:
        pet = self.current_pet()
        if not pet:
            return self.empty_message("Sem timeline", "Adicione um animal para criar o histórico.")
        timeline = build_timeline(pet)
        controls: list[ft.Control] = []
        for item in timeline:
            controls.append(
                ft.Row(
                    [
                        ft.Container(width=10, height=10, border_radius=5, bgcolor=ACCENT),
                        ft.Column(
                            [
                                ft.Text(human_date(item["date"]), size=12, color=ACCENT_DARK),
                                ft.Text(item["title"], weight=ft.FontWeight.BOLD),
                                ft.Text(item["kind"], size=12, opacity=0.6),
                            ], expand=True, spacing=1,
                        ),
                    ], vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )
            controls.append(ft.Divider(height=8))
        if not controls:
            controls = [ft.Text("Ainda não existem eventos na cronologia.", opacity=0.7)]
        return ft.Column(
            [
                self.header("Cronologia", "Histórico de saúde e eventos", self.pet_selector()),
                self.panel(ft.Column(controls, spacing=6), bgcolor="#F9FBFA"),
                ft.Container(height=16),
            ], scroll=ft.ScrollMode.AUTO, expand=True, spacing=12,
        )

    # -----------------------------
    # Documents
    # -----------------------------
    def documents_view(self) -> ft.Control:
        pet = self.current_pet()
        if not pet:
            return self.empty_message("Sem documentos", "Adicione um animal para criar a biblioteca documental.")
        docs = sorted(pet.get("documents", []), key=lambda x: x.get("date", x.get("created_at", "")), reverse=True)
        controls: list[ft.Control] = []
        for doc in docs:
            size_kb = int(doc.get("size", 0) or 0) / 1024
            controls.append(
                self.panel(
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, color=ACCENT),
                            ft.Column(
                                [
                                    ft.Text(doc.get("name", "Documento"), weight=ft.FontWeight.BOLD),
                                    ft.Text(f"{doc.get('category', 'Outros')} · {human_date(doc.get('date'))} · {size_kb:.0f} KB", size=12, opacity=0.7),
                                    ft.Text(short(doc.get("notes", ""), 100), size=11) if doc.get("notes") else ft.Container(),
                                ], expand=True, spacing=2,
                            ),
                            ft.IconButton(icon=ft.Icons.DOWNLOAD, tooltip="Guardar ficheiro", on_click=lambda _, d=doc: self.page.run_task(self.save_document_file, d)),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=DANGER, tooltip="Eliminar", on_click=lambda _, d=doc: self.delete_document(d)),
                        ]
                    ), bgcolor="#F7FAF9"
                )
            )
        if not controls:
            controls = [ft.Text("Ainda não existem documentos para este animal.", opacity=0.7)]
        return ft.Column(
            [
                self.header("Documentos", "Passaporte, vacinas, receitas, exames, seguros e outros", self.pet_selector()),
                ft.FilledButton(
                    content="Adicionar documento",
                    icon=ft.Icons.UPLOAD_FILE,
                    action=ft.PickFiles(
                        self.document_picker,
                        allow_multiple=False,
                        with_data=True,
                        cancel_upload_on_window_blur=False,
                    ),
                ),
                ft.Column(controls, spacing=8),
                ft.Container(height=16),
            ], scroll=ft.ScrollMode.AUTO, expand=True, spacing=12,
        )

    async def on_document_picked(self, e) -> None:
        pet = self.current_pet()
        if not pet:
            return
        files = list(e.files or [])
        if not files:
            return
        f = files[0]
        if not f.bytes:
            self.snack("Não foi possível ler o ficheiro.")
            return
        limit = min(MAX_ATTACHMENT_BYTES, 1500 * 1024) if self.page.web else MAX_ATTACHMENT_BYTES
        if len(f.bytes) > limit:
            self.snack("Ficheiro demasiado grande. Limite: 1,5 MB na web e 5 MB nas apps instaladas.")
            return
        initial = {"name": f.name, "category": "Outros", "date": today_iso(), "notes": ""}
        fields = [("name", "Nome", "text"), ("category", "Categoria", "text"), ("date", "Data", "date"), ("notes", "Notas", "multiline")]

        async def save(values):
            rec = make_record(**values)
            rec.update({
                "mime": "application/octet-stream",
                "size": len(f.bytes),
            })
            if self.page.web:
                rec["data_b64"] = base64.b64encode(f.bytes).decode("ascii")
            else:
                rec["storage_path"] = store_attachment_bytes(f.bytes, f.name)
            pet["documents"].append(rec)
            touch(pet)
            await self.save_state()
            self.render()

        await self.open_form("Adicionar documento", fields, initial, save)

    async def save_document_file(self, doc: dict[str, Any]) -> None:
        try:
            data = read_document_bytes(doc)
        except Exception:
            self.snack("O anexo está danificado ou indisponível.")
            return
        await ft.FilePicker().save_file(file_name=safe_filename(doc.get("name", "documento.bin")), src_bytes=data)

    def delete_document(self, doc: dict[str, Any]) -> None:
        pet = self.current_pet()
        if not pet:
            return

        async def do_delete():
            delete_document_file(doc)
            delete_record(pet, "documents", doc.get("id", ""))
            await self.save_state()
            self.render()

        self.confirm("Eliminar documento", f"Eliminar “{doc.get('name', 'documento')}” e o respetivo anexo?", do_delete, danger=True)

    # -----------------------------
    # QR / emergency
    # -----------------------------
    def show_qr(self) -> None:
        pet = self.current_pet()
        if not pet:
            return
        text = emergency_text(pet, self.state.get("owner", {}))
        qr = make_qr_svg_bytes(text)
        dlg = ft.AlertDialog(
            title=ft.Text(f"QR — {pet.get('name', '')}"),
            content=ft.Column(
                [
                    ft.Image(src=qr, width=240, height=240),
                    ft.Text("Qualquer leitor de QR consegue mostrar estes dados essenciais, mesmo sem instalar a aplicação.", size=12, text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True,
            ),
            actions=[ft.TextButton(content="Fechar", on_click=lambda _: self.page.pop_dialog())],
        )
        self.page.show_dialog(dlg)

    def show_emergency(self) -> None:
        pet = self.current_pet()
        if not pet:
            return
        owner = self.state.get("owner", {})
        allergies = "\n".join(f"• {a.get('name', '')}: {a.get('reaction', '')}" for a in pet.get("allergies", [])) or "Nenhuma alergia registada"
        conditions = "\n".join(f"• {c.get('name', '')}: {c.get('treatment', '')}" for c in pet.get("conditions", [])) or "Nenhuma condição registada"
        meds = "\n".join(f"• {m.get('name', '')} — {m.get('dose', '')}" for m in active_medications(pet)) or "Nenhuma medicação ativa"
        text = (
            f"MICROCHIP\n{pet.get('microchip', {}).get('number', '') or 'Não registado'}\n\n"
            f"ALERGIAS\n{allergies}\n\nCONDIÇÕES\n{conditions}\n\nMEDICAÇÃO\n{meds}\n\n"
            f"TUTOR\n{owner.get('name', '')}\n{owner.get('phone', '')}\n\n"
            f"VETERINÁRIO\n{pet.get('veterinary', {}).get('clinic', '')}\n{pet.get('veterinary', {}).get('emergency_phone', '') or pet.get('veterinary', {}).get('phone', '')}"
        )
        dlg = ft.AlertDialog(
            title=ft.Text(f"EMERGÊNCIA — {pet.get('name', '')}", color=DANGER, size=24, weight=ft.FontWeight.BOLD),
            content=ft.Container(width=560, height=520, content=ft.Column([ft.Text(text, size=17, selectable=True)], scroll=ft.ScrollMode.AUTO)),
            actions=[ft.FilledButton(content="Fechar", on_click=lambda _: self.page.pop_dialog(), bgcolor=DANGER, color="#FFFFFF")],
        )
        self.page.show_dialog(dlg)

    # -----------------------------
    # More / settings / owner / backup
    # -----------------------------
    def more_view(self) -> ft.Control:
        pet = self.current_pet()
        stat = f"{len(self.state.get('pets', []))} animal(is)"
        if pet:
            stat += f" · {len(pet.get('documents', []))} documento(s)"
        return ft.Column(
            [
                self.header("Mais", f"Pet Passport {APP_VERSION} · {stat}"),
                self.panel(
                    ft.Column(
                        [
                            ft.ListTile(leading=ft.Icon(ft.Icons.PERSON_OUTLINE), title=ft.Text("Dados do tutor"), subtitle=ft.Text(self.state.get("owner", {}).get("name", "Não definido") or "Não definido"), on_click=lambda _: self.page.run_task(self.edit_owner)),
                            ft.ListTile(leading=ft.Icon(ft.Icons.SEARCH), title=ft.Text("Pesquisa universal"), subtitle=ft.Text("Pesquisar em todos os registos"), on_click=lambda _: self.search_dialog()),
                            ft.ListTile(leading=ft.Icon(ft.Icons.PALETTE_OUTLINED), title=ft.Text("Aparência"), subtitle=ft.Text(f"Tema: {self.state.get('settings', {}).get('theme', 'system')}"), on_click=lambda _: self.theme_dialog()),
                            ft.ListTile(leading=ft.Icon(ft.Icons.PIN_OUTLINED), title=ft.Text("PIN de acesso"), subtitle=ft.Text("Definir, alterar ou remover"), on_click=lambda _: self.pin_dialog()),
                            ft.ListTile(leading=ft.Icon(ft.Icons.FINGERPRINT), title=ft.Text("Biometria"), subtitle=ft.Text("Ativada" if self.state.get("settings", {}).get("biometric_enabled") else "Desativada"), on_click=lambda _: self.page.run_task(self.biometric_dialog)),
                        ], spacing=2,
                    ), bgcolor="#F7FAF9"
                ),
                ft.Text("Backup e exportação", size=18, weight=ft.FontWeight.BOLD),
                self.panel(
                    ft.Column(
                        [
                            ft.ListTile(leading=ft.Icon(ft.Icons.ARCHIVE_OUTLINED), title=ft.Text("Exportar backup ZIP"), subtitle=ft.Text("Inclui JSON, CSV, PDF e anexos"), on_click=lambda _: self.page.run_task(self.export_backup_zip)),
                            ft.ListTile(leading=ft.Icon(ft.Icons.DATA_OBJECT), title=ft.Text("Exportar JSON"), subtitle=ft.Text("Cópia integral dos dados estruturados"), on_click=lambda _: self.page.run_task(self.export_json)),
                            ft.ListTile(
                                leading=ft.Icon(ft.Icons.RESTORE),
                                title=ft.Text("Importar backup"),
                                subtitle=ft.Text("Restaurar ficheiro .zip ou .json"),
                                action=ft.PickFiles(
                                    self.backup_picker,
                                    allow_multiple=False,
                                    with_data=True,
                                    file_type=ft.FilePickerFileType.CUSTOM,
                                    allowed_extensions=["zip", "json"],
                                    cancel_upload_on_window_blur=False,
                                ),
                            ),
                            ft.ListTile(leading=ft.Icon(ft.Icons.PICTURE_AS_PDF), title=ft.Text("Relatório PDF do animal"), subtitle=ft.Text(pet.get("name", "") if pet else "Sem animal selecionado"), disabled=pet is None, on_click=lambda _: self.page.run_task(self.export_pet_pdf)),
                        ], spacing=2,
                    ), bgcolor="#F7FAF9"
                ),
                ft.Text("Privacidade", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Os dados são guardados localmente através do armazenamento seguro da plataforma. A aplicação não exige conta nem envia automaticamente informação para a cloud. "
                    "No navegador, utilize HTTPS e cabeçalhos de segurança ao publicar a aplicação.",
                    size=12,
                    opacity=0.7,
                ),
                ft.Container(height=18),
            ], scroll=ft.ScrollMode.AUTO, expand=True, spacing=12,
        )

    async def edit_owner(self) -> None:
        fields = [
            ("name", "Nome do tutor", "text"), ("address", "Morada", "multiline"), ("country", "País", "text"),
            ("phone", "Telefone", "text"), ("alt_phone", "Telefone alternativo", "text"),
            ("email", "Email", "text"), ("emergency_contact", "Contacto de emergência", "text"),
        ]

        async def save(values):
            self.state["owner"].update(values)
            await self.save_state()
            self.render()

        await self.open_form("Dados do tutor", fields, self.state.get("owner", {}), save)

    def theme_dialog(self) -> None:
        async def set_theme(mode: str):
            self.state["settings"]["theme"] = mode
            self.apply_theme()
            await self.save_state()
            self.page.pop_dialog()
            self.render()

        dlg = ft.AlertDialog(
            title=ft.Text("Aparência"),
            content=ft.Column(
                [
                    ft.FilledButton(content="Automático", icon=ft.Icons.BRIGHTNESS_AUTO, on_click=lambda _: self.page.run_task(set_theme, "system")),
                    ft.OutlinedButton(content="Claro", icon=ft.Icons.LIGHT_MODE, on_click=lambda _: self.page.run_task(set_theme, "light")),
                    ft.OutlinedButton(content="Escuro", icon=ft.Icons.DARK_MODE, on_click=lambda _: self.page.run_task(set_theme, "dark")),
                ], tight=True,
            ),
        )
        self.page.show_dialog(dlg)

    def pin_dialog(self) -> None:
        p1 = ft.TextField(label="Novo PIN (4 a 12 dígitos)", password=True, can_reveal_password=True, keyboard_type=ft.KeyboardType.NUMBER, max_length=12)
        p2 = ft.TextField(label="Repetir PIN", password=True, can_reveal_password=True, keyboard_type=ft.KeyboardType.NUMBER, max_length=12)
        error = ft.Text("", color=DANGER)

        async def set_pin(_):
            a, b = (p1.value or "").strip(), (p2.value or "").strip()
            if not (a.isdigit() and 4 <= len(a) <= 12):
                error.value = "Use entre 4 e 12 dígitos."
                self.page.update()
                return
            if a != b:
                error.value = "Os PINs não coincidem."
                self.page.update()
                return
            await self.storage.set(key=PIN_KEY, value=make_pin_hash(a))
            self.page.pop_dialog()
            self.snack("PIN definido com sucesso.")

        async def remove_pin(_):
            await self.storage.remove(key=PIN_KEY)
            self.page.pop_dialog()
            self.snack("PIN removido.")

        dlg = ft.AlertDialog(
            title=ft.Text("PIN de acesso"),
            content=ft.Column([p1, p2, error], tight=True),
            actions=[
                ft.TextButton(content="Remover PIN", on_click=remove_pin),
                ft.FilledButton(content="Guardar PIN", on_click=set_pin),
            ],
        )
        self.page.show_dialog(dlg)

    async def biometric_dialog(self) -> None:
        if self.page.web:
            self.snack("A autenticação biométrica não está disponível na versão web. Use PIN.")
            return
        try:
            supported = await self.local_auth.is_device_supported()
            can = await self.local_auth.can_check_biometrics()
        except Exception:
            supported, can = False, False
        if not supported:
            self.snack("Este dispositivo não disponibiliza autenticação local compatível.")
            return
        current = bool(self.state["settings"].get("biometric_enabled"))

        async def toggle(_):
            if not current:
                try:
                    ok = await self.local_auth.authenticate("Confirmar ativação da biometria", biometric_only=False)
                    if not ok:
                        return
                except Exception:
                    self.snack("Não foi possível validar a autenticação local.")
                    return
            self.state["settings"]["biometric_enabled"] = not current
            await self.save_state()
            self.page.pop_dialog()
            self.render()

        dlg = ft.AlertDialog(
            title=ft.Text("Biometria"),
            content=ft.Text(f"Suporte do dispositivo: sim. Biometria detetável: {'sim' if can else 'não/indisponível'}. Estado atual: {'ativada' if current else 'desativada'}."),
            actions=[
                ft.TextButton(content="Cancelar", on_click=lambda _: self.page.pop_dialog()),
                ft.FilledButton(content="Desativar" if current else "Ativar", icon=ft.Icons.FINGERPRINT, on_click=toggle),
            ],
        )
        self.page.show_dialog(dlg)

    def search_dialog(self) -> None:
        field = ft.TextField(label="Pesquisar", autofocus=True, prefix_icon=ft.Icons.SEARCH)

        def run(_):
            self.page.pop_dialog()
            self.show_search_results(field.value or "")

        dlg = ft.AlertDialog(
            title=ft.Text("Pesquisa universal"),
            content=field,
            actions=[ft.FilledButton(content="Pesquisar", icon=ft.Icons.SEARCH, on_click=run)],
        )
        self.page.show_dialog(dlg)

    def show_search_results(self, query: str) -> None:
        results = search_state(self.state, query)
        controls: list[ft.Control] = []
        for r in results:
            controls.append(
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.SEARCH),
                    title=ft.Text(r["title"]),
                    subtitle=ft.Text(f"{r['subtitle']} · {r['section']}"),
                    on_click=lambda _, x=r: self.go_to_search_result(x),
                )
            )
        if not controls:
            controls = [ft.Text("Nenhum resultado encontrado.", opacity=0.7)]
        dlg = ft.AlertDialog(
            title=ft.Text(f"Resultados — “{query}”"),
            content=ft.Container(width=600, height=440, content=ft.Column(controls, scroll=ft.ScrollMode.AUTO)),
            actions=[ft.TextButton(content="Fechar", on_click=lambda _: self.page.pop_dialog())],
        )
        self.page.show_dialog(dlg)

    def go_to_search_result(self, result: dict[str, str]) -> None:
        self.active_pet_id = result.get("pet_id")
        self.page.pop_dialog()
        section = result.get("section", "")
        reverse = {
            "Vacinas": "vaccines", "Medicação": "medications", "Consultas": "appointments",
            "Alergias": "allergies", "Condições": "conditions", "Cirurgias": "surgeries",
            "Exames": "exams", "Lembretes": "reminders",
        }
        if section == "Documentos":
            self.nav_index = 3
            self.render()
        elif section == "Viagens":
            self.open_travel_view()
        elif section in reverse:
            self.open_record_section(reverse[section])
        else:
            self.nav_index = 1
            self.render()

    async def export_pet_pdf(self, _=None) -> None:
        pet = self.current_pet()
        if not pet:
            self.snack("Selecione um animal.")
            return
        data = make_pet_pdf(pet, self.state.get("owner", {}))
        await ft.FilePicker().save_file(
            file_name=f"Pet_Passport_{safe_filename(pet.get('name', 'Animal'))}.pdf",
            allowed_extensions=["pdf"],
            file_type=ft.FilePickerFileType.CUSTOM,
            src_bytes=data,
        )

    async def export_backup_zip(self, _=None) -> None:
        data = make_backup_zip(self.state)
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        await ft.FilePicker().save_file(
            file_name=f"PetPassport_backup_{stamp}.zip",
            allowed_extensions=["zip"],
            file_type=ft.FilePickerFileType.CUSTOM,
            src_bytes=data,
        )

    async def export_json(self, _=None) -> None:
        data = json.dumps(self.state, ensure_ascii=False, indent=2).encode("utf-8")
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        await ft.FilePicker().save_file(
            file_name=f"PetPassport_{stamp}.json",
            allowed_extensions=["json"],
            file_type=ft.FilePickerFileType.CUSTOM,
            src_bytes=data,
        )

    async def on_backup_picked(self, e) -> None:
        files = list(e.files or [])
        if not files:
            return
        f = files[0]
        if not f.bytes:
            self.snack("Não foi possível ler o backup.")
            return
        try:
            restored = restore_backup_bytes(f.bytes, f.name)
        except Exception as exc:
            self.snack(f"Backup inválido: {exc}")
            return

        async def restore():
            self.state = restored if self.page.web else materialize_attachments_to_files(restored)
            self.active_pet_id = self.state["pets"][0]["id"] if self.state.get("pets") else None
            await self.save_state()
            self.apply_theme()
            self.render()
            self.snack("Backup restaurado com sucesso.")

        self.confirm(
            "Restaurar backup",
            "A restauração substitui todos os dados atuais do Pet Passport neste dispositivo. O ficheiro selecionado parece válido. Pretende continuar?",
            restore,
            danger=True,
        )

    # -----------------------------
    # Destructive pet operation
    # -----------------------------
    def delete_current_pet(self) -> None:
        pet = self.current_pet()
        if not pet:
            return

        async def do_delete():
            delete_pet_files(pet)
            self.state["pets"] = [p for p in self.state.get("pets", []) if p.get("id") != pet.get("id")]
            self.active_pet_id = self.state["pets"][0]["id"] if self.state.get("pets") else None
            await self.save_state()
            self.nav_index = 0
            self.render()

        self.confirm("Eliminar animal", f"Eliminar definitivamente o perfil de {pet.get('name', 'este animal')} e todos os seus registos e anexos?", do_delete, danger=True)


async def main(page: ft.Page):
    app = PetPassportApp(page)
    await app.start()


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
