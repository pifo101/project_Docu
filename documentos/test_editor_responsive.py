from html.parser import HTMLParser
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse


class EditorMarkup(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.elements = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def with_attribute(self, attribute):
        return [(tag, attrs) for tag, attrs in self.elements if attribute in attrs]


class EditorResponsiveTemplateTests(SimpleTestCase):
    def render_editor(self, backend=False):
        context = {"destinatarios": [], "destinatarios_editor": []}
        if backend:
            context["documento"] = SimpleNamespace(pk=17, nombre_original="acta.pdf")
        return EditorMarkup(render_to_string("documentos/editor.html", context))

    def test_single_palette_contains_exactly_the_six_tools(self):
        for backend in (False, True):
            with self.subTest(backend=backend):
                markup = self.render_editor(backend)
                tools = markup.with_attribute("data-field-type")
                self.assertEqual(len(tools), 6)
                self.assertEqual(
                    {attrs["data-field-type"] for _, attrs in tools},
                    {"signature", "name", "date", "text", "initials", "checkbox"},
                )
                self.assertTrue(all(tag == "button" and attrs["type"] == "button"
                                    and "disabled" in attrs for tag, attrs in tools))
                ids = [attrs["id"] for _, attrs in markup.with_attribute("id")]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(ids.count("editor-field-list"), 1)
                self.assertEqual(ids.count("editor-field-properties"), 1)

    def test_mobile_toggles_reference_existing_panels(self):
        markup = self.render_editor()
        for attribute, panel in (
            ("data-tools-open", "editor-tools-drawer"),
            ("data-properties-toggle", "editor-field-properties"),
        ):
            with self.subTest(attribute=attribute):
                elements = markup.with_attribute(attribute)
                self.assertEqual(len(elements), 1)
                tag, attrs = elements[0]
                self.assertEqual(tag, "button")
                self.assertEqual(attrs["type"], "button")
                self.assertEqual(attrs["aria-expanded"], "false")
                self.assertEqual(attrs["aria-controls"], panel)
                self.assertIn("disabled", attrs)
        self.assertEqual(len(markup.with_attribute("data-properties-close")), 1)
        # Sin FAB: no debe existir el toggle antiguo ni herramienta duplicada.
        self.assertEqual(markup.with_attribute("data-fields-toggle"), [])
        drawer_tools = markup.with_attribute("data-drawer-field-type")
        self.assertEqual(len(drawer_tools), 6)
        self.assertEqual(
            {attrs["data-drawer-field-type"] for _, attrs in drawer_tools},
            {"signature", "name", "date", "text", "initials", "checkbox"},
        )
        self.assertEqual(len(markup.with_attribute("data-tools-drawer")), 1)
        self.assertEqual(len(markup.with_attribute("data-drawer-backdrop")), 1)
        self.assertEqual(len(markup.with_attribute("data-drawer-close")), 1)

    def test_properties_are_not_duplicated_and_placement_is_announced(self):
        markup = self.render_editor()
        for attribute in (
            "data-properties-content", "data-property-recipient", "data-property-required",
            "data-property-label", "data-property-delete",
        ):
            self.assertEqual(len(markup.with_attribute(attribute)), 1)
        self.assertIn("hidden", markup.with_attribute("data-placement")[0][1])
        message = markup.with_attribute("data-placement-message")[0][1]
        self.assertEqual(message["role"], "status")
        self.assertEqual(message["aria-live"], "polite")
        cancel = markup.with_attribute("data-placement-cancel")
        self.assertEqual(len(cancel), 1)
        self.assertEqual(cancel[0][1]["type"], "button")

    def test_backend_retains_single_save_and_existing_endpoints(self):
        self.assertEqual(self.render_editor().with_attribute("data-editor-save"), [])
        markup = self.render_editor(backend=True)
        save = markup.with_attribute("data-editor-save")
        self.assertEqual(len(save), 1)
        self.assertIn("disabled", save[0][1])
        shell = markup.with_attribute("data-editor-backend")[0][1]
        self.assertEqual(shell["data-fields-url"], reverse("documentos:signature_fields", args=[17]))
        proceed = markup.with_attribute("data-editor-continue")
        self.assertEqual(len(proceed), 1)
        self.assertEqual(proceed[0][1]["data-review-url"], reverse("documentos:send_review", args=[17]))
