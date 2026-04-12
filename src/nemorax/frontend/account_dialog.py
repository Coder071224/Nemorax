"""
frontend/account_dialog.py
--------------------------
Account UI panel - register, log in, forgot password, guest mode, logout.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import flet as ft

from nemorax.frontend import api_client
from nemorax.frontend.config import current_theme


RECOVERY_QUESTIONS = [
    "favorite color",
    "favorite food",
    "favorite animal",
    "favorite place",
    "favorite subject",
    "childhood nickname",
    "mother's maiden name",
]
REQUIRED_RECOVERY = 2
_MAX_REGISTER_RECOVERY_FIELDS = 5
_PANEL_RADIUS = 28
_PANEL_PADDING = 24
_PANEL_MAX_WIDTH = 440


UserInfo = dict[str, Any]


class AccountDialog:
    _VIEW_LANDING = "landing"
    _VIEW_LOGIN = "login"
    _VIEW_REGISTER = "register"
    _VIEW_FORGOT_EMAIL = "forgot_email"
    _VIEW_FORGOT_ANSWERS = "forgot_answers"
    _VIEW_FORGOT_RESET = "forgot_reset"
    _VIEW_LOGGED_IN = "logged_in"

    def __init__(
        self,
        *,
        page: ft.Page,
        current_user: UserInfo | None,
        is_mobile: bool,
        on_login: Callable[[UserInfo], None],
        on_logout: Callable[[], None],
        on_guest: Callable[[], None],
        on_user_update: Callable[[UserInfo], None],
    ) -> None:
        self._page = page
        self._current_user = current_user
        self._is_mobile = is_mobile
        self._on_login = on_login
        self._on_logout = on_logout
        self._on_guest = on_guest
        self._on_user_update = on_user_update

        self._view = self._VIEW_LOGGED_IN if current_user else self._VIEW_LANDING
        self._error_text = ""
        self._success_text = ""

        self._login_email_value = ""
        self._login_password_value = ""
        self._login_locked = False
        self._login_loading = False

        self._fp_email = ""
        self._fp_questions: list[str] = []
        self._display_name_value = self._normalize_display_name(
            current_user.get("display_name") if current_user else None
        )
        self._saved_display_name_value = self._display_name_value
        self._profile_loading = False
        self._display_name_saving = False

        self._overlay_container: ft.Container | None = None
        self._content_ref = ft.Ref[ft.Container]()
        self._display_name_field_ref = ft.Ref[ft.TextField]()
        self._display_name_save_ref = ft.Ref[ft.Button]()
        self._display_name_remove_ref = ft.Ref[ft.TextButton]()

    def open(self) -> None:
        self._overlay_container = self._build_overlay()
        self._page.overlay.append(self._overlay_container)
        self._page.update()
        if self._current_user:
            self._load_user_profile()

    def _close(self, e=None) -> None:
        if self._overlay_container in self._page.overlay:
            self._page.overlay.remove(self._overlay_container)
        self._page.update()

    def _safe_update(self, control: ft.Control | None) -> None:
        if control is None:
            return
        try:
            if control.page is not None:
                control.update()
        except Exception:
            pass

    def _run_on_ui(self, callback: Callable[[], None]) -> None:
        async def _runner() -> None:
            callback()

        self._page.run_task(_runner)

    def _run_in_thread(self, worker: Callable[[], None]) -> None:
        threading.Thread(target=worker, daemon=True).start()

    def _open_dialog(self, dialog: ft.AlertDialog) -> None:
        if dialog not in self._page.overlay:
            self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def _close_dialog(self, dialog: ft.AlertDialog | None) -> None:
        if dialog is None:
            return
        dialog.open = False
        if dialog in self._page.overlay:
            self._page.overlay.remove(dialog)
        self._page.update()

    def _show_history_info_dialog(self) -> None:
        theme = current_theme()
        dialog: ft.AlertDialog | None = None

        def close(e=None) -> None:
            self._close_dialog(dialog)

        dialog = ft.AlertDialog(
            bgcolor=theme.dialog_bg,
            shape=ft.RoundedRectangleBorder(radius=24),
            title=ft.Text(
                "Conversation History",
                color=theme.text_primary,
                weight=ft.FontWeight.W_800,
            ),
            content=ft.Container(
                width=360,
                padding=ft.Padding.all(4),
                content=ft.Column(
                    spacing=12,
                    tight=True,
                    controls=[
                        ft.Text(
                            "Your conversations are saved automatically and accessible from the sidebar. "
                            "To manage or remove a conversation, see the instructions below based on your device.",
                            size=12.5,
                            color=theme.text_secondary,
                        ),
                        ft.Text(
                            "Desktop & Web",
                            size=12.5,
                            weight=ft.FontWeight.W_700,
                            color=theme.text_primary,
                        ),
                        ft.Text(
                            "Right-click any conversation in the sidebar to reveal options.",
                            size=12,
                            color=theme.text_secondary,
                        ),
                        ft.Text(
                            "Mobile (Android & iOS)",
                            size=12.5,
                            weight=ft.FontWeight.W_700,
                            color=theme.text_primary,
                        ),
                        ft.Text(
                            "Press and hold any conversation in the sidebar to reveal options.",
                            size=12,
                            color=theme.text_secondary,
                        ),
                    ],
                ),
            ),
            actions=[
                ft.TextButton(
                    "Close",
                    on_click=close,
                    style=ft.ButtonStyle(color=theme.accent),
                )
            ],
        )
        self._open_dialog(dialog)

    def _normalize_display_name(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()[:30]

    def _current_display_name_input(self) -> str:
        if self._display_name_field_ref.current is not None:
            return self._normalize_display_name(self._display_name_field_ref.current.value or "")
        return self._display_name_value

    def _sync_display_name_actions(self) -> None:
        current_value = self._current_display_name_input()
        self._display_name_value = current_value

        if self._display_name_field_ref.current is not None:
            self._display_name_field_ref.current.disabled = (
                self._profile_loading or self._display_name_saving
            )
            self._safe_update(self._display_name_field_ref.current)

        if self._display_name_save_ref.current is not None:
            self._display_name_save_ref.current.disabled = (
                self._profile_loading
                or self._display_name_saving
                or current_value == self._saved_display_name_value
            )
            self._safe_update(self._display_name_save_ref.current)

        if self._display_name_remove_ref.current is not None:
            self._display_name_remove_ref.current.visible = bool(current_value)
            self._display_name_remove_ref.current.disabled = (
                self._profile_loading or self._display_name_saving
            )
            self._safe_update(self._display_name_remove_ref.current)

    def _apply_profile(self, profile: UserInfo, *, notify_parent: bool) -> None:
        self._current_user = profile
        self._view = self._VIEW_LOGGED_IN
        self._display_name_value = self._normalize_display_name(profile.get("display_name"))
        self._saved_display_name_value = self._display_name_value
        if notify_parent:
            self._on_user_update(profile)

    def _load_user_profile(self) -> None:
        user_id = str((self._current_user or {}).get("user_id", "")).strip()
        if not user_id:
            return

        self._profile_loading = True
        self._refresh_content()

        def _worker() -> None:
            profile = api_client.load_user_profile(user_id)

            def _apply() -> None:
                self._profile_loading = False
                if profile:
                    self._apply_profile(profile, notify_parent=True)
                self._refresh_content()

            self._run_on_ui(_apply)

        self._run_in_thread(_worker)

    def _save_display_name(self, display_name: str | None, *, removed: bool = False) -> None:
        user_id = str((self._current_user or {}).get("user_id", "")).strip()
        if not user_id:
            self._set_error("Unable to update nickname right now.")
            return

        self._display_name_saving = True
        self._error_text = ""
        self._success_text = ""
        self._refresh_content()

        def _worker() -> None:
            profile, error = api_client.save_display_name(user_id, display_name)

            def _apply() -> None:
                self._display_name_saving = False
                if profile:
                    self._apply_profile(profile, notify_parent=True)
                    self._set_success("Nickname removed." if removed else "Nickname updated.")
                    return

                self._set_error(error or "Unable to update nickname.")

            self._run_on_ui(_apply)

        self._run_in_thread(_worker)

    def _navigate(self, view: str) -> None:
        self._view = view
        self._error_text = ""
        self._success_text = ""

        if view == self._VIEW_LOGIN and self._current_user is None:
            self._login_email_value = ""
            self._login_password_value = ""
            self._login_locked = False
            self._login_loading = False

        self._refresh_content()

    def _set_error(self, message: str) -> None:
        self._error_text = message
        self._success_text = ""
        self._refresh_content()

    def _set_success(self, message: str) -> None:
        self._success_text = message
        self._error_text = ""
        self._refresh_content()

    def _refresh_content(self) -> None:
        if self._content_ref.current is None:
            return

        self._content_ref.current.content = self._build_view()
        self._safe_update(self._content_ref.current)

    def _page_size(self) -> tuple[float, float]:
        return float(self._page.width or 400), float(self._page.height or 700)

    def _panel_width(self, page_width: float) -> float:
        return page_width if self._is_mobile else min(page_width - 60, _PANEL_MAX_WIDTH)

    def _panel_radius(self) -> ft.BorderRadius:
        if self._is_mobile:
            return ft.BorderRadius.only(top_left=_PANEL_RADIUS, top_right=_PANEL_RADIUS)
        return ft.BorderRadius.all(_PANEL_RADIUS)

    def _build_overlay(self) -> ft.Container:
        theme = current_theme()
        page_width, page_height = self._page_size()

        panel = ft.Container(
            width=self._panel_width(page_width),
            bgcolor=theme.dialog_bg,
            border_radius=self._panel_radius(),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.20, theme.border)),
            shadow=ft.BoxShadow(
                blur_radius=40,
                color=ft.Colors.with_opacity(0.38, theme.shadow),
                offset=ft.Offset(0, -6 if self._is_mobile else 12),
            ),
            padding=ft.Padding.all(_PANEL_PADDING),
            content=ft.Container(ref=self._content_ref, content=self._build_view()),
        )

        return ft.Container(
            expand=True,
            width=page_width,
            height=page_height,
            bgcolor=ft.Colors.with_opacity(0.52, "#000000"),
            on_click=self._close,
            alignment=ft.Alignment(0, 1 if self._is_mobile else 0),
            content=ft.GestureDetector(on_tap=lambda _: None, content=panel),
        )

    def _build_view(self) -> ft.Control:
        if self._view == self._VIEW_LOGGED_IN:
            return self._view_logged_in()
        if self._view == self._VIEW_LOGIN:
            return self._view_login()
        if self._view == self._VIEW_REGISTER:
            return self._view_register()
        if self._view == self._VIEW_FORGOT_EMAIL:
            return self._view_forgot_email()
        if self._view == self._VIEW_FORGOT_ANSWERS:
            return self._view_forgot_answers()
        if self._view == self._VIEW_FORGOT_RESET:
            return self._view_forgot_reset()
        return self._view_landing()

    def _field(
        self,
        hint: str,
        *,
        password: bool = False,
        value: str = "",
        disabled: bool = False,
        label: str | None = None,
        ref: ft.Ref[ft.TextField] | None = None,
        on_change: Callable[..., None] | None = None,
        on_submit: Callable[..., None] | None = None,
        max_length: int | None = None,
    ) -> ft.TextField:
        theme = current_theme()
        return ft.TextField(
            ref=ref,
            value=value,
            label=label,
            hint_text=hint,
            hint_style=ft.TextStyle(color=theme.text_muted),
            password=password,
            can_reveal_password=password,
            bgcolor=ft.Colors.with_opacity(0.18, theme.surface_alt),
            color=theme.text_primary,
            border_radius=14,
            border_color=ft.Colors.with_opacity(0.22, theme.border),
            focused_border_color=theme.accent,
            cursor_color=theme.accent,
            text_size=14,
            content_padding=ft.Padding.symmetric(horizontal=16, vertical=14),
            disabled=disabled,
            on_change=on_change,
            on_submit=on_submit,
            max_length=max_length,
        )

    def _primary_btn(
        self,
        label: str,
        on_click: Callable[..., None],
        *,
        disabled: bool = False,
    ) -> ft.Button:
        theme = current_theme()
        return ft.Button(
            content=ft.Text(
                label,
                size=13,
                weight=ft.FontWeight.W_700,
                color="#081018",
            ),
            style=ft.ButtonStyle(
                bgcolor=theme.accent,
                shape=ft.RoundedRectangleBorder(radius=14),
                elevation=0,
                padding=ft.Padding.symmetric(horizontal=24, vertical=14),
            ),
            on_click=on_click,
            width=float("inf"),
            disabled=disabled,
        )

    def _secondary_btn(
        self,
        label: str,
        on_click: Callable[..., None],
    ) -> ft.OutlinedButton:
        theme = current_theme()
        return ft.OutlinedButton(
            content=ft.Text(
                label,
                size=13,
                weight=ft.FontWeight.W_600,
                color=theme.text_primary,
            ),
            style=ft.ButtonStyle(
                side=ft.BorderSide(1, ft.Colors.with_opacity(0.30, theme.border)),
                shape=ft.RoundedRectangleBorder(radius=14),
                padding=ft.Padding.symmetric(horizontal=24, vertical=14),
            ),
            on_click=on_click,
            width=float("inf"),
        )

    def _title(self, text: str) -> ft.Text:
        return ft.Text(
            text,
            size=22,
            weight=ft.FontWeight.W_800,
            color=current_theme().text_primary,
        )

    def _subtitle(self, text: str) -> ft.Text:
        return ft.Text(text, size=13, color=current_theme().text_secondary)

    def _feedback_row(self) -> ft.Control:
        theme = current_theme()

        if self._error_text:
            return ft.Container(
                bgcolor=ft.Colors.with_opacity(0.12, theme.error),
                border_radius=12,
                border=ft.Border.all(1, ft.Colors.with_opacity(0.30, theme.error)),
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.ERROR_OUTLINE, size=16, color=theme.error),
                        ft.Text(self._error_text, size=12, color=theme.error, expand=True),
                    ],
                    spacing=8,
                ),
            )

        if self._success_text:
            return ft.Container(
                bgcolor=ft.Colors.with_opacity(0.14, theme.success),
                border_radius=12,
                border=ft.Border.all(1, ft.Colors.with_opacity(0.35, theme.success)),
                padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.CHECK_CIRCLE_OUTLINE,
                            size=18,
                            color=theme.success,
                        ),
                        ft.Text(
                            self._success_text,
                            size=13,
                            color=theme.success,
                            weight=ft.FontWeight.W_600,
                            expand=True,
                        ),
                    ],
                    spacing=8,
                ),
            )

        return ft.Container(height=0)

    def _back_row(self, label: str, target: str) -> ft.Control:
        theme = current_theme()
        return ft.TextButton(
            content=ft.Row(
                controls=[
                    ft.Icon(
                        ft.Icons.ARROW_BACK_IOS_ROUNDED,
                        size=13,
                        color=theme.accent,
                    ),
                    ft.Text(label, size=12, color=theme.accent),
                ],
                spacing=4,
                tight=True,
            ),
            on_click=lambda _: self._navigate(target),
        )

    def _link_btn(
        self,
        label: str,
        on_click: Callable[..., None],
    ) -> ft.TextButton:
        return ft.TextButton(
            content=ft.Text(label, size=12, color=current_theme().accent),
            on_click=on_click,
        )

    def _close_btn(self) -> ft.IconButton:
        return ft.IconButton(
            icon=ft.Icons.CLOSE_ROUNDED,
            icon_color=current_theme().text_secondary,
            on_click=self._close,
        )

    def _header_icon(self, icon: ft.IconData) -> ft.Container:
        theme = current_theme()
        return ft.Container(
            width=44,
            height=44,
            border_radius=14,
            bgcolor=ft.Colors.with_opacity(0.14, theme.accent),
            alignment=ft.Alignment(0, 0),
            content=ft.Icon(icon, color=theme.accent, size=22),
        )

    def _header_row(
        self,
        *,
        title: str,
        subtitle: str,
        icon: ft.IconData = ft.Icons.PERSON_ROUNDED,
    ) -> ft.Row:
        return ft.Row(
            controls=[
                self._header_icon(icon),
                ft.Column(
                    controls=[self._title(title), self._subtitle(subtitle)],
                    spacing=2,
                    tight=True,
                    expand=True,
                ),
                self._close_btn(),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _section_top_row(self, back_label: str, target: str) -> ft.Row:
        return ft.Row(
            controls=[
                self._back_row(back_label, target),
                ft.Container(expand=True),
                self._close_btn(),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _view_landing(self) -> ft.Control:
        return ft.Column(
            controls=[
                self._header_row(
                    title="Account",
                    subtitle="Sign in or continue as guest",
                ),
                ft.Container(height=20),
                self._primary_btn("Log In", lambda _: self._navigate(self._VIEW_LOGIN)),
                ft.Container(height=8),
                self._primary_btn("Sign Up", lambda _: self._navigate(self._VIEW_REGISTER)),
                ft.Container(height=8),
                self._secondary_btn("Continue as Guest", self._handle_guest),
            ],
            spacing=0,
            tight=True,
        )

    def _view_login(self) -> ft.Control:
        theme = current_theme()
        locked = self._login_locked
        loading = self._login_loading

        email_field = self._field(
            "Email address",
            value=self._login_email_value,
            disabled=locked or loading,
        )
        password_field = self._field(
            "Password",
            password=True,
            value=self._login_password_value,
            disabled=locked or loading,
        )

        def submit(e=None) -> None:
            if locked or loading:
                return

            email = (email_field.value or "").strip()
            password = (password_field.value or "").strip()
            self._login_email_value = email
            self._login_password_value = password

            if not email or not password:
                self._set_error("Please fill in all fields.")
                return

            self._login_loading = True
            self._error_text = ""
            self._success_text = ""
            self._refresh_content()

            def _worker() -> None:
                user, message = api_client.auth_login(email, password)

                def _apply() -> None:
                    self._login_loading = False

                    if user:
                        self._apply_profile(user, notify_parent=False)
                        self._login_locked = True
                        self._login_email_value = email
                        self._login_password_value = ""
                        self._set_success("You are now successfully logged in.")
                        self._on_login(user)
                        return

                    self._login_locked = False
                    self._login_email_value = email
                    self._login_password_value = ""
                    self._set_error(message or "Incorrect email or password. Please try again.")

                self._run_on_ui(_apply)

            self._run_in_thread(_worker)

        button_label = "Signing in..." if loading else ("Logged In" if locked else "Log In")

        login_button = ft.Button(
            content=ft.Row(
                controls=[
                    ft.ProgressRing(
                        width=16,
                        height=16,
                        stroke_width=2,
                        visible=loading,
                    ),
                    ft.Text(
                        button_label,
                        size=13,
                        weight=ft.FontWeight.W_700,
                        color="#081018",
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=10,
            ),
            style=ft.ButtonStyle(
                bgcolor=current_theme().success if locked else theme.accent,
                shape=ft.RoundedRectangleBorder(radius=14),
                elevation=0,
                padding=ft.Padding.symmetric(horizontal=24, vertical=14),
            ),
            on_click=submit,
            width=float("inf"),
            disabled=locked or loading,
        )

        return ft.Column(
            controls=[
                self._section_top_row("Back", self._VIEW_LANDING),
                ft.Container(height=8),
                self._title("Log In"),
                self._subtitle("Welcome back to Nemorax"),
                ft.Container(height=16),
                email_field,
                ft.Container(height=10),
                password_field,
                ft.Container(height=6),
                ft.Row(
                    controls=[
                        ft.Container(expand=True),
                        self._link_btn(
                            "Forgot password?",
                            lambda _: None if locked else self._navigate(self._VIEW_FORGOT_EMAIL),
                        ),
                    ],
                ),
                ft.Container(height=4),
                self._feedback_row(),
                ft.Container(height=12),
                login_button,
                ft.Container(height=10),
                ft.Row(
                    controls=[
                        self._subtitle("Don't have an account?"),
                        self._link_btn(
                            "Sign Up",
                            lambda _: None if locked else self._navigate(self._VIEW_REGISTER),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=4,
                ),
            ],
            spacing=0,
            tight=True,
        )

    def _view_register(self) -> ft.Control:
        theme = current_theme()
        email_field = self._field("Email address")
        password_field = self._field("Password (min 6 chars)", password=True)
        confirm_field = self._field("Confirm password", password=True)

        recovery_fields: dict[str, ft.TextField] = {}
        recovery_controls: list[ft.Control] = []

        for index, question in enumerate(RECOVERY_QUESTIONS[:_MAX_REGISTER_RECOVERY_FIELDS]):
            hint = (
                f"Your {question} "
                f"{'(required)' if index < REQUIRED_RECOVERY else '(optional)'}"
            )
            field = self._field(hint)
            recovery_fields[question] = field
            recovery_controls.extend(
                [
                    ft.Text(
                        question.title(),
                        size=12,
                        color=theme.text_muted,
                        weight=ft.FontWeight.W_600,
                    ),
                    field,
                    ft.Container(height=6),
                ]
            )

        def submit(e=None) -> None:
            email = (email_field.value or "").strip()
            password = (password_field.value or "").strip()
            confirm = (confirm_field.value or "").strip()

            if not email or not password or not confirm:
                self._set_error("Please fill in email and password fields.")
                return

            if password != confirm:
                self._set_error("Passwords do not match.")
                return

            answers = {
                question: (field.value or "").strip()
                for question, field in recovery_fields.items()
                if (field.value or "").strip()
            }
            if len(answers) < REQUIRED_RECOVERY:
                self._set_error(
                    f"Please fill in at least {REQUIRED_RECOVERY} recovery answers."
                )
                return

            def _worker() -> None:
                ok, message = api_client.auth_register(email, password, answers)

                def _apply() -> None:
                    if ok:
                        self._login_email_value = email
                        self._login_password_value = ""
                        self._navigate(self._VIEW_LOGIN)
                        self._set_success("Account created. You can now log in.")
                        return

                    self._set_error(message)

                self._run_on_ui(_apply)

            self._run_in_thread(_worker)

        return ft.Column(
            controls=[
                self._section_top_row("Back", self._VIEW_LANDING),
                ft.Container(height=8),
                self._title("Create Account"),
                self._subtitle("Join Nemorax and save your chats"),
                ft.Container(height=16),
                email_field,
                ft.Container(height=10),
                password_field,
                ft.Container(height=10),
                confirm_field,
                ft.Container(height=16),
                ft.Text(
                    "Recovery Answers",
                    size=13,
                    weight=ft.FontWeight.W_700,
                    color=theme.text_secondary,
                ),
                ft.Text(
                    f"Fill at least {REQUIRED_RECOVERY} - used if you forget your password.",
                    size=11,
                    color=theme.text_muted,
                ),
                ft.Container(height=10),
                *recovery_controls,
                self._feedback_row(),
                ft.Container(height=12),
                self._primary_btn("Create Account", submit),
                ft.Container(height=10),
                ft.Row(
                    controls=[
                        self._subtitle("Already have an account?"),
                        self._link_btn("Log In", lambda _: self._navigate(self._VIEW_LOGIN)),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=4,
                ),
            ],
            spacing=0,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            height=min(float(self._page.height or 700) * 0.82, 560),
        )

    def _view_forgot_email(self) -> ft.Control:
        email_field = self._field("Enter your account email")

        def next_step(e=None) -> None:
            email = (email_field.value or "").strip()
            if not email:
                self._set_error("Please enter your email address.")
                return

            def _worker() -> None:
                questions, error = api_client.auth_get_recovery_questions(email)

                def _apply_error() -> None:
                    self._set_error(error or "No account found for this email.")

                def _apply_success() -> None:
                    self._fp_email = email
                    self._fp_questions = questions
                    self._navigate(self._VIEW_FORGOT_ANSWERS)

                self._run_on_ui(_apply_success if questions else _apply_error)

            self._run_in_thread(_worker)

        return ft.Column(
            controls=[
                self._section_top_row("Back to Login", self._VIEW_LOGIN),
                ft.Container(height=8),
                self._title("Forgot Password"),
                self._subtitle("Enter your email to start password recovery"),
                ft.Container(height=16),
                email_field,
                ft.Container(height=4),
                self._feedback_row(),
                ft.Container(height=12),
                self._primary_btn("Continue", next_step),
            ],
            spacing=0,
            tight=True,
        )

    def _view_forgot_answers(self) -> ft.Control:
        theme = current_theme()
        answer_fields: dict[str, ft.TextField] = {}
        field_controls: list[ft.Control] = []

        for question in self._fp_questions:
            field = self._field(f"Your {question}")
            answer_fields[question] = field
            field_controls.extend(
                [
                    ft.Text(
                        question.title(),
                        size=12,
                        color=theme.text_muted,
                        weight=ft.FontWeight.W_600,
                    ),
                    field,
                    ft.Container(height=8),
                ]
            )

        def verify(e=None) -> None:
            answers = {
                question: (field.value or "").strip()
                for question, field in answer_fields.items()
            }
            if sum(1 for value in answers.values() if value) < REQUIRED_RECOVERY:
                self._set_error(f"Please answer at least {REQUIRED_RECOVERY} questions.")
                return

            def _worker() -> None:
                ok, message = api_client.auth_verify_recovery(self._fp_email, answers)

                def _apply() -> None:
                    if ok:
                        self._navigate(self._VIEW_FORGOT_RESET)
                    else:
                        self._set_error(message)

                self._run_on_ui(_apply)

            self._run_in_thread(_worker)

        return ft.Column(
            controls=[
                self._section_top_row("Back", self._VIEW_FORGOT_EMAIL),
                ft.Container(height=8),
                self._title("Verify Identity"),
                self._subtitle(f"Answer your recovery questions for {self._fp_email}"),
                ft.Container(height=16),
                *field_controls,
                self._feedback_row(),
                ft.Container(height=12),
                self._primary_btn("Verify Answers", verify),
            ],
            spacing=0,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            height=min(float(self._page.height or 700) * 0.72, 480),
        )

    def _view_forgot_reset(self) -> ft.Control:
        new_password_field = self._field("New password (min 6 chars)", password=True)
        confirm_field = self._field("Confirm new password", password=True)

        def reset(e=None) -> None:
            password = (new_password_field.value or "").strip()
            confirm = (confirm_field.value or "").strip()

            if not password or not confirm:
                self._set_error("Please fill in both fields.")
                return

            if password != confirm:
                self._set_error("Passwords do not match.")
                return

            def _worker() -> None:
                ok, message = api_client.auth_reset_password(self._fp_email, password)

                def _apply() -> None:
                    if ok:
                        self._login_email_value = self._fp_email
                        self._navigate(self._VIEW_LOGIN)
                        self._set_success("Password reset! You can now log in.")
                    else:
                        self._set_error(message)

                self._run_on_ui(_apply)

            self._run_in_thread(_worker)

        return ft.Column(
            controls=[
                self._section_top_row("Back", self._VIEW_FORGOT_ANSWERS),
                ft.Container(height=8),
                self._title("Reset Password"),
                self._subtitle(f"Set a new password for {self._fp_email}"),
                ft.Container(height=16),
                new_password_field,
                ft.Container(height=10),
                confirm_field,
                ft.Container(height=4),
                self._feedback_row(),
                ft.Container(height=12),
                self._primary_btn("Reset Password", reset),
            ],
            spacing=0,
            tight=True,
        )

    def _view_logged_in(self) -> ft.Control:
        theme = current_theme()
        user = self._current_user or {}
        email = str(user.get("email", ""))
        user_id = str(user.get("user_id", ""))

        def logout(e=None) -> None:
            self._close()
            self._on_logout()

        def handle_display_name_change(e: ft.ControlEvent) -> None:
            self._display_name_value = self._normalize_display_name(e.control.value or "")
            self._sync_display_name_actions()

        def save_display_name(e=None) -> None:
            value = self._current_display_name_input()
            if len(value) > 30:
                self._set_error("Nickname must be 30 characters or fewer.")
                return
            if value == self._saved_display_name_value:
                return
            self._save_display_name(value or None)

        def remove_display_name(e=None) -> None:
            if self._display_name_field_ref.current is not None:
                self._display_name_field_ref.current.value = ""
                self._safe_update(self._display_name_field_ref.current)
            self._display_name_value = ""
            self._sync_display_name_actions()
            self._save_display_name(None, removed=True)

        nickname_field = self._field(
            "e.g. Ivan, Ace, Pathfinder...",
            value=self._display_name_value,
            disabled=self._profile_loading or self._display_name_saving,
            ref=self._display_name_field_ref,
            on_change=handle_display_name_change,
            on_submit=save_display_name,
            max_length=30,
        )

        save_button = ft.Button(
            ref=self._display_name_save_ref,
            content=ft.Text(
                "Saving..." if self._display_name_saving else "Save",
                size=12,
                weight=ft.FontWeight.W_700,
                color="#081018",
            ),
            style=ft.ButtonStyle(
                bgcolor=theme.accent,
                shape=ft.RoundedRectangleBorder(radius=12),
                elevation=0,
                padding=ft.Padding.symmetric(horizontal=18, vertical=10),
            ),
            on_click=save_display_name,
            disabled=(
                self._profile_loading
                or self._display_name_saving
                or self._display_name_value == self._saved_display_name_value
            ),
        )

        remove_button = ft.TextButton(
            ref=self._display_name_remove_ref,
            content=ft.Text("Remove", size=12, color=theme.error),
            on_click=remove_display_name,
            visible=bool(self._display_name_value),
            disabled=self._profile_loading or self._display_name_saving,
        )

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        self._header_icon(ft.Icons.PERSON_ROUNDED),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "Signed In",
                                    size=12,
                                    weight=ft.FontWeight.W_700,
                                    color=theme.success,
                                ),
                                ft.Text(
                                    email,
                                    size=14,
                                    weight=ft.FontWeight.W_700,
                                    color=theme.text_primary,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                            ],
                            spacing=1,
                            tight=True,
                            expand=True,
                        ),
                        self._close_btn(),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=16),
                ft.Container(
                    bgcolor=ft.Colors.with_opacity(0.10, theme.accent),
                    border_radius=16,
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.20, theme.accent)),
                    padding=ft.Padding.all(14),
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons.EMAIL_OUTLINED,
                                        size=14,
                                        color=theme.text_muted,
                                    ),
                                    ft.Text("Email", size=11, color=theme.text_muted, width=56),
                                    ft.Text(
                                        email,
                                        size=12,
                                        color=theme.text_primary,
                                        expand=True,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons.TAG_ROUNDED,
                                        size=14,
                                        color=theme.text_muted,
                                    ),
                                    ft.Text("ID", size=11, color=theme.text_muted, width=56),
                                    ft.Text(
                                        f"{user_id[:16]}..." if len(user_id) > 16 else user_id,
                                        size=12,
                                        color=theme.text_secondary,
                                        expand=True,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Container(
                                border_radius=12,
                                on_click=lambda _: self._show_history_info_dialog(),
                                content=ft.Row(
                                    controls=[
                                        ft.Icon(
                                            ft.Icons.SAVE_OUTLINED,
                                            size=14,
                                            color=theme.success,
                                        ),
                                        ft.Text("", size=11, color=theme.text_muted, width=56),
                                        ft.Text(
                                            "History is being saved",
                                            size=12,
                                            color=theme.success,
                                            expand=True,
                                        ),
                                        ft.Container(
                                            width=18,
                                            height=18,
                                            alignment=ft.Alignment(0, 0),
                                            border_radius=9,
                                            border=ft.Border.all(
                                                1,
                                                ft.Colors.with_opacity(0.45, theme.success),
                                            ),
                                            content=ft.Text(
                                                "?",
                                                size=10,
                                                weight=ft.FontWeight.W_700,
                                                color=theme.success,
                                            ),
                                        ),
                                    ],
                                    spacing=8,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ),
                        ],
                        spacing=10,
                    ),
                ),
                ft.Container(height=16),
                ft.Container(
                    bgcolor=ft.Colors.with_opacity(0.08, theme.surface_alt),
                    border_radius=16,
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.18, theme.border)),
                    padding=ft.Padding.all(14),
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        "What should we call you?",
                                        size=13,
                                        weight=ft.FontWeight.W_700,
                                        color=theme.text_primary,
                                    ),
                                    ft.Container(
                                        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                                        border_radius=999,
                                        bgcolor=ft.Colors.with_opacity(0.12, theme.accent),
                                        content=ft.Text(
                                            "Optional",
                                            size=10,
                                            weight=ft.FontWeight.W_700,
                                            color=theme.accent,
                                        ),
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Container(height=10),
                            nickname_field,
                            ft.Container(height=10),
                            ft.Row(
                                controls=[
                                    save_button,
                                    remove_button,
                                    ft.Container(expand=True),
                                    ft.Row(
                                        visible=self._profile_loading,
                                        controls=[
                                            ft.ProgressRing(width=14, height=14, stroke_width=2),
                                            ft.Text(
                                                "Loading profile...",
                                                size=11,
                                                color=theme.text_muted,
                                            ),
                                        ],
                                        spacing=8,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=0,
                        tight=True,
                    ),
                ),
                ft.Container(height=16),
                self._feedback_row(),
                ft.Container(height=16 if (self._error_text or self._success_text) else 0),
                ft.Button(
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.LOGOUT_ROUNDED,
                                size=16,
                                color=theme.error,
                            ),
                            ft.Text(
                                "Log Out",
                                size=13,
                                weight=ft.FontWeight.W_700,
                                color=theme.error,
                            ),
                        ],
                        spacing=8,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.with_opacity(0.10, theme.error),
                        side=ft.BorderSide(1, ft.Colors.with_opacity(0.30, theme.error)),
                        shape=ft.RoundedRectangleBorder(radius=14),
                        elevation=0,
                        padding=ft.Padding.symmetric(horizontal=24, vertical=14),
                    ),
                    on_click=logout,
                    width=float("inf"),
                ),
            ],
            spacing=0,
            tight=True,
        )

    def _handle_guest(self, e=None) -> None:
        self._close()
        self._on_guest()

