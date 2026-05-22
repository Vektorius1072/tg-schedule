import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("GROUP_CHAT_ID", "-1000000000000")

import api  # noqa: E402


class ApiFormattingTests(unittest.TestCase):
    def test_format_day_escapes_html(self):
        lessons = [
            {
                "order": 1,
                "title": "<script>alert(1)</script>",
                "teacher": "A & B",
                "cabinet": "101 <A>",
                "startTime": "08:30:00",
                "endTime": "10:00:00",
            }
        ]
        text = api.format_day(lessons, api.datetime(2026, 5, 25))
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertIn("A &amp; B", text)
        self.assertIn("101 &lt;A&gt;", text)
        self.assertNotIn("<script>", text)

    def test_format_day_with_error(self):
        text = api.format_day([], api.datetime(2026, 5, 25), error="Network down")
        self.assertIn("⚠️", text)
        self.assertIn("Network down", text)


class ApiAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_format_tomorrow_uses_schedule(self):
        with patch.object(
            api,
            "get_schedule",
            AsyncMock(
                return_value=[
                    {
                        "lessons": [
                            {
                                "order": 2,
                                "title": "Math",
                                "teacher": "Teacher",
                                "cabinet": "202",
                                "startTime": "10:15:00",
                                "endTime": "11:45:00",
                            }
                        ]
                    }
                ]
            ),
        ):
            text = await api.format_tomorrow(113)
        self.assertIn("Math", text)
        self.assertIn("10:15-11:45", text)

    async def test_get_week_schedule_marks_failed_day(self):
        call_state = {"idx": 0}

        async def fake_get_schedule(group_id: int, date: str, client=None):
            del group_id, date, client
            call_state["idx"] += 1
            if call_state["idx"] == 1:
                raise RuntimeError("API failure")
            return [{"lessons": []}]

        with patch.object(api, "get_schedule", side_effect=fake_get_schedule):
            week = await api.get_week_schedule(113)

        self.assertEqual(len(week), 6)
        self.assertEqual(week[0].error, "Не удалось загрузить расписание")
        self.assertIsNone(week[1].error)


if __name__ == "__main__":
    unittest.main()
