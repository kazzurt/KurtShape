"""Exclusive tool state and invalidation without discarding user drafts."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kurtshape.tool_session import ToolSession


class ToolSessionTests(unittest.TestCase):
    def test_exclusivity_and_kind_specific_clear(self):
        session = ToolSession()
        owner = ("document", "sketch", object())
        session.select("native", "Sketcher_CreateCircle", owner)
        token = session.generation
        self.assertFalse(session.clear("reference"))
        self.assertTrue(session.current(token))
        session.select("reference", ("document", "sketch"), owner)
        self.assertFalse(session.current(token))
        self.assertEqual(session.state.kind, "reference")
        self.assertTrue(session.clear("reference"))
        self.assertFalse(session.active)

    def test_context_loss_and_same_tool_restart_invalidate_callbacks(self):
        session = ToolSession()
        owner = object()
        session.select("dimension", "selection", owner)
        state, token = session.state, session.generation
        session.invalidate_callbacks()
        self.assertIs(session.state, state)
        self.assertFalse(session.current(token))
        token = session.generation
        session.select("dimension", "selection", owner)
        self.assertFalse(session.current(token))
        self.assertEqual(session.state, state)

    def test_invalid_activation_preserves_tool_and_close_rejects_late_callbacks(self):
        session = ToolSession()
        session.select("native", "Sketcher_CreateCircle", object())
        state, token = session.state, session.generation
        for kind, owner in (("unknown", object()), ("dimension", None)):
            with self.assertRaises(ValueError):
                session.select(kind, "value", owner)
        self.assertIs(session.state, state)
        self.assertTrue(session.current(token))
        session.close()
        generation = session.generation
        session.close()
        self.assertEqual(session.generation, generation)
        self.assertFalse(session.current(token))
        with self.assertRaises(RuntimeError):
            session.select("native", "Sketcher_CreateCircle", object())
