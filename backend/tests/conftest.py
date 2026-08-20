"""Test-environment isolation, applied before ANY app module is imported.

`app.config.settings` is built once, at first import. Setting these in a test
module is a trap: whichever test file pytest happens to import first decides
whether the override landed, and when it didn't, the suite read and WROTE the
real dev database and media directory (x.mp4 posts in the feed came from here).
conftest is imported before every test module, so the override always wins.
"""

from __future__ import annotations

import os
import tempfile

_scratch = tempfile.mkdtemp(prefix="razorwire-tests-")

os.environ.setdefault("DEV_AUTH_EMAIL", "tester@razorpay.com")
os.environ["DATABASE_URL"] = "sqlite://"  # in-memory, per process
os.environ["MEDIA_DIR"] = os.path.join(_scratch, "media")
os.environ["WORK_DIR"] = os.path.join(_scratch, "work")
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
