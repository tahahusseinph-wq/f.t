"""المساعد الذكي: اسأل بياناتك بالعربية."""
from __future__ import annotations

import html

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QTextBrowser

from ftapp.services import gemini_service
from ftapp.ui.pages.base import Page
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import Card, button, muted
from ftapp.ui.widgets.worker import run_async

EXAMPLES = [
    "شو أكتر 5 منتجات مبيعاً هالشهر؟",
    "قديش صافي الربح هالشهر مقارنة بالشهر الماضي؟",
    "أي قسم عم يربّح أكتر؟",
    "شو المنتجات اللي لازم أطلبها هالأسبوع؟",
    "مين أكتر زبون عليه دين؟",
    "شو البضاعة الراكدة اللي لازم أعمل عليها عرض؟",
]


class AIPage(Page):
    title = "المساعد الذكي"
    subtitle = "اسأل عن مبيعاتك ومخزونك بلغتك العادية (Gemini)"

    def __init__(self) -> None:
        super().__init__()
        self.history: list[tuple[str, str]] = []
        card = Card()
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        self.chat.setStyleSheet("border: none;")
        card.add(self.chat, 1)
        chips = QHBoxLayout()
        for q in EXAMPLES[:4]:
            b = QPushButton(q)
            b.setProperty("variant", "chip")
            b.clicked.connect(lambda _=False, text=q: self._ask(text))
            chips.addWidget(b)
        chips.addStretch(1)
        card.body.addLayout(chips)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setObjectName("searchBox")
        self.input.setMinimumHeight(44)
        self.input.setPlaceholderText("اكتب سؤالك هنا ثم Enter...")
        self.input.returnPressed.connect(lambda: self._ask(self.input.text()))
        row.addWidget(self.input, 1)
        self.send = button("إرسال", "send", "primary", on_click=lambda: self._ask(self.input.text()))
        row.addWidget(self.send)
        card.body.addLayout(row)
        self.root.addWidget(card, 1)
        self.root.addWidget(muted("يعتمد المساعد على ملخص لبياناتك (مبيعات، أرباح، مخزون، ديون) ويُرسل إلى Gemini للإجابة. "
                                  "لا يستطيع المساعد تعديل أي بيانات."))
        self._welcome()

    def _welcome(self) -> None:
        if not gemini_service.is_configured():
            self.chat.setHtml("<p style='color:#E53935'>لم يتم إدخال مفتاح Gemini بعد. أضفه من الإعدادات ← الذكاء الاصطناعي.</p>")
        else:
            self.chat.setHtml("<h3>أهلاً 👋</h3><p>اسألني عن مبيعاتك، أرباحك، مخزونك أو ديون الزبائن.</p>")

    def _bubble(self, text: str, mine: bool) -> None:
        t = tokens()
        bg = t["primary_soft"] if mine else t["surface2"]
        who = "أنت" if mine else "✨ المساعد"
        body = html.escape(text).replace("\n", "<br>")
        self.chat.append(f"<table width='100%' cellpadding='10'><tr><td style='background:{bg}; border-radius:10px'>"
                         f"<b>{who}</b><br>{body}</td></tr></table>")
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def _ask(self, question: str) -> None:
        question = question.strip()
        if not question:
            return
        self.input.clear()
        self._bubble(question, True)
        self.send.setEnabled(False)
        self.input.setEnabled(False)
        history = list(self.history)

        def work():
            from ftapp.core.db import session_scope
            with session_scope() as s:
                return gemini_service.ask_data(s, question, history)

        def done(ans) -> None:
            text = ans.answer
            if ans.highlights:
                text += "\n\n" + "\n".join(f"• {h}" for h in ans.highlights)
            self.history.append((question, ans.answer))
            self._bubble(text, False)
            self._unlock()

        def fail(msg: str) -> None:
            self._bubble(f"⚠ {msg}", False)
            self._unlock()
        run_async(work, done, fail)

    def _unlock(self) -> None:
        self.send.setEnabled(True)
        self.input.setEnabled(True)
        self.input.setFocus()
