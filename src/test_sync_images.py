# ponytail: 동기화 그림 self-check — 사용자 이름이 다른 PC끼리 그림이 보이는지, 같은 그림은 한 번만,
# 못 받은 그림 자리 표시, 너무 큰 그림, 안 쓰는 그림 정리. 임시 폴더만 쓴다. run: python src/test_sync_images.py
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = Path(tempfile.mkdtemp())
import database  # noqa: E402

database.APP_DIR, database.IMAGES_DIR = tmp, tmp / "images"
from PyQt6.QtCore import QUrl  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QTextDocument  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import memo_document  # noqa: E402
from database import MemoDatabase  # noqa: E402
from sync import images  # noqa: E402
from sync.core import DAY_MS  # noqa: E402
from sync.engine import IMAGE_KEEP_DAYS, Syncer  # noqa: E402
from sync.local_folder import LocalFolderTransport  # noqa: E402
from sync.store import SyncStore  # noqa: E402

app = QApplication([])
T0 = 1_762_000_000_000


class Clock:
    def __init__(self, ms):
        self.ms = ms

    def __call__(self):
        self.ms += 1
        return self.ms


class PC:
    """PC 한 대. 사용자 이름마다 그림 폴더가 다르다 (C:/Users/<이름>/.memo_slide/images)."""

    def __init__(self, user, drive):
        self.user = user
        self.images = tmp / "Users" / user / ".memo_slide" / "images"
        self.images.mkdir(parents=True)
        self.clock = Clock(T0)
        with self:
            self.db = MemoDatabase(tmp / f"{user}.db")
            self.store = SyncStore(self.db.conn, self.clock)
            self.store.connect("me@example.com")
            self.syncer = Syncer(self.store, LocalFolderTransport(drive), user)

    def __enter__(self):
        database.IMAGES_DIR = self.images  # 이 PC의 그림 폴더로
        return self

    def __exit__(self, *exc):
        return False

    def sync(self):
        with self:
            return self.syncer.sync()

    def paste(self, name, color, size=(40, 30)):
        """붙여 넣기와 같다: 그림 폴더에 img_….png로 저장하고 본문에 절대 경로로 넣는다."""
        path = self.images / name
        img = QImage(*size, QImage.Format.Format_RGB32)
        img.fill(QColor(color))
        for x in range(0, size[0], 7):  # 무늬를 넣어 크기를 키운다
            img.setPixelColor(x, (x * 13) % size[1], QColor("#ffffff"))
        assert img.save(str(path), "PNG")
        return f'<p>그림:<img src="{path.as_posix()}" width="40" /></p>'

    def memo(self, uid):
        return next(m for m in self.db.list_all() + self.db.list_trashed_memos() if m.uid == uid)


def drive_images():
    return sorted(p.name for p in drive.iterdir() if p.name.startswith("img_"))


def settle(*pcs):
    for _ in range(2):
        for pc in pcs:
            pc.sync()


drive = tmp / "drive"
A, B = PC("alice", drive), PC("bob", drive)

# ----- 같은 그림이 다른 파일 이름으로 두 번 → Drive에는 한 번 -----
red1 = A.paste("img_20261111_090000_000001.png", "#cc3333")
red2 = A.paste("img_20261111_090500_000002.png", "#cc3333")   # 같은 그림, 다른 이름
m1 = A.db.create("빨간 그림", red1)
m2 = A.db.create("같은 그림 또", red2)
blue = A.paste("img_20261111_091000_000003.png", "#3333cc")
m3 = A.db.create("파란 그림", blue)
settle(A, B)
assert len(drive_images()) == 2, drive_images()
sha_red = images.sha256_file(A.images / "img_20261111_090000_000001.png")
assert f"img_{sha_red}.png" in drive_images()

# ----- 사용자 이름이 다른 PC에서 그림이 보인다 -----
for m in (m1, m2, m3):
    html = B.memo(m.uid).content
    assert "/alice/" not in html and "smimg:" not in html, html
    (path,) = images.local_paths_in(html, B.images)
    assert path.exists() and QImage(str(path)).width() == 40, path
assert A.memo(m1.uid).content == red1, "A의 본문 경로는 그대로"
assert sorted(p.name for p in B.images.iterdir()) == sorted([f"{sha_red}.png", f"{images.sha256_file(A.images / 'img_20261111_091000_000003.png')}.png"]), "B도 같은 그림은 한 파일"

# B가 글자만 고쳐도 A의 그림 경로는 바뀌지 않고, 주고받기가 되풀이되지 않는다
B.db.update(B.memo(m1.uid).id, content=B.memo(m1.uid).content.replace("그림:", "빨간 그림:"))
settle(A, B)
assert "빨간 그림:" in A.memo(m1.uid).content and "img_20261111_090000_000001.png" in A.memo(m1.uid).content
for pc in (A, B):
    with pc:
        assert pc.store.reconcile() == [] and pc.store.pending() == []

# ----- 그림을 아직 못 받음: 본문 먼저, 자리 표시, 다음 동기화에 채움 -----
green = A.paste("img_20261111_092000_000004.png", "#33aa33")
sha_green = images.sha256_file(A.images / "img_20261111_092000_000004.png")
m4 = A.db.create("초록 그림", green)
real_write = A.syncer.transport.write
A.syncer.transport.write = lambda name, data: None if name.startswith("img_") else real_write(name, data)
A.sync()                         # 기록만 올라가고 그림은 못 올라감
A.syncer.transport.write = real_write
B.sync()
html = B.memo(m4.uid).content
(path,) = images.local_paths_in(html, B.images)
assert not path.exists() and B.syncer.arrived == [], "그림은 아직 없다"
with B:
    assert B.store.reconcile() == [], "받을 자리 경로가 다시 기록을 만들면 안 된다"

doc = QTextDocument()
doc.setHtml(html)
assert memo_document.fill_missing_images(doc) == 1
url = QUrl(path.as_posix())
ph = doc.resource(QTextDocument.ResourceType.ImageResource, url)
assert isinstance(ph, QImage) and ph.width() == 440, "자리 표시가 들어가야 한다"
saved_before = memo_document.saved_html(doc)

# 메모를 열어 둔 창에서 그림이 도착해도 깨지지 않는다
import main as M  # noqa: E402

win = M.SlideMemoWindow(B.db)
win._load_memo(B.memo(m4.uid))
win.expand()
open_before = memo_document.saved_html(win.editor.document())
A.sync()                         # 이번엔 그림도 올라간다
B.sync()
assert B.syncer.arrived == [path] and path.exists()
assert memo_document.refresh_images(doc, B.syncer.arrived)
real = doc.resource(QTextDocument.ResourceType.ImageResource, url)
assert real.width() == 40, "받은 그림으로 바뀌어야 한다"
assert memo_document.saved_html(doc) == saved_before, "그림이 와도 저장 내용은 같다"
win.images_arrived(B.syncer.arrived)
app.processEvents()
shown = win.editor.document().resource(QTextDocument.ResourceType.ImageResource, url)
assert shown.width() == 40, "열려 있는 메모에도 그림이 들어온다"
assert memo_document.saved_html(win.editor.document()) == open_before
win.save_now()
assert B.memo(m4.uid).content == html, "그림이 와서 메모가 저장되면 안 된다"
win._quitting = True
win.close()
B.db = MemoDatabase(tmp / "bob.db")       # 창이 닫으며 DB를 닫았다
with B:
    B.store = SyncStore(B.db.conn, B.clock)
    B.syncer = Syncer(B.store, LocalFolderTransport(drive), "bob")

# ----- 너무 큰 그림: 건너뛰고 표시, 5MB 기준으로 올리는 길이 갈린다 -----
large_calls = []
for pc in (A, B):
    pc.syncer.transport.write_large = (lambda real: lambda n, d: (large_calls.append(n), real(n, d)))(pc.syncer.transport.write)
saved_limits = images.MAX_IMAGE_BYTES, images.LARGE_UPLOAD_BYTES
huge = A.paste("img_20261111_093000_000005.png", "#000000", (900, 700))
mid = A.paste("img_20261111_093500_000006.png", "#ffffff")
sha_huge = images.sha256_file(A.images / "img_20261111_093000_000005.png")
sha_mid = images.sha256_file(A.images / "img_20261111_093500_000006.png")
size_huge = (A.images / "img_20261111_093000_000005.png").stat().st_size
images.LARGE_UPLOAD_BYTES = 10                         # 시험용으로 기준을 낮춘다
images.MAX_IMAGE_BYTES = size_huge - 1                 # 검은 그림만 '너무 큼'
assert (A.images / "img_20261111_093500_000006.png").stat().st_size <= images.MAX_IMAGE_BYTES
m5 = A.db.create("큰 그림", huge + mid)
settle(A, B)
images.MAX_IMAGE_BYTES, images.LARGE_UPLOAD_BYTES = saved_limits
assert f"img_{sha_huge}.png" not in drive_images() and f"img_{sha_mid}.png" in drive_images()
assert f"img_{sha_mid}.png" in large_calls, "기준을 넘는 그림은 큰 파일 길로"
assert A.store.get_json("too_big_local", []) == [sha_huge], "보낸 PC는 못 보낸 그림을 안다"
assert sha_huge in B.syncer.too_big_remote(), "받은 PC도 너무 커서 못 받는다는 걸 안다"
memo_document.too_big_images = B.syncer.too_big_remote()
doc = QTextDocument()
doc.setHtml(B.memo(m5.uid).content)
assert memo_document.fill_missing_images(doc) == 1
(big_path,) = [p for p in images.local_paths_in(B.memo(m5.uid).content, B.images) if not p.exists()]
assert big_path.stem == sha_huge

# ----- 안 쓰는 그림 정리 (180일) -----
# 파란 그림: A에서 메모를 지운다 → 어느 메모도 안 씀 → 180일 뒤 Drive와 두 PC에서 지운다
# 빨간 그림: A에서 지워도 B 휴지통 메모(m2)가 쓰고 있으면 남는다
# 초록 그림: 어느 메모도 안 쓰지만 A의 이전 버전이 쓴다 → Drive에서는 지우고 A 파일은 남긴다
sha_blue = images.sha256_file(A.images / "img_20261111_091000_000003.png")
A.db.delete(A.memo(m3.uid).id)
A.db.delete(A.memo(m1.uid).id)
B.db.soft_delete(B.memo(m2.uid).id)
a_m4 = A.memo(m4.uid)
A.db.conn.execute("INSERT INTO memo_versions (memo_id, title, content, created_at) VALUES (?, ?, ?, 'x')",
                  (a_m4.id, "옛 버전", a_m4.content))
A.db.conn.commit()
A.db.update(a_m4.id, content="<p>그림을 뺐다</p>")
settle(A, B)
for pc in (A, B):
    with pc:
        assert pc.syncer.cleanup_images(force=True) == ([], []), "처음 본 날에는 지우지 않는다"
for pc in (A, B):
    pc.clock.ms += (IMAGE_KEEP_DAYS - 1) * DAY_MS
    with pc:
        assert pc.syncer.cleanup_images(force=True) == ([], []), "보관 기간 전"
A.clock.ms += 2 * DAY_MS
with A:
    gone_drive, gone_local = A.syncer.cleanup_images(force=True)
assert set(gone_drive) == {sha_blue, sha_green}, gone_drive
assert {p.name for p in gone_local} == {"img_20261111_091000_000003.png"}, gone_local
assert (A.images / "img_20261111_092000_000004.png").exists(), "이전 버전이 쓰는 그림은 이 PC에 남는다"
assert f"img_{sha_red}.png" in drive_images(), "다른 PC 휴지통 메모가 쓰는 그림은 남는다"
assert (A.images / "img_20261111_090500_000002.png").exists() or (A.images / "img_20261111_090000_000001.png").exists()
B.clock.ms += 2 * DAY_MS
with B:
    _, gone_b = B.syncer.cleanup_images(force=True)
assert {p.name for p in gone_b} >= {f"{sha_blue}.png", f"{sha_green}.png"}, gone_b
assert (B.images / f"{sha_red}.png").exists()

# 지워진 그림을 아직 쓰는 PC가 있으면 다음 올리기에서 다시 올라간다
(drive / f"img_{sha_red}.png").unlink()
A.sync()
assert f"img_{sha_red}.png" in drive_images(), "쓰는 PC가 다시 올린다"

app.quit()
shutil.rmtree(tmp, ignore_errors=True)
print("sync images OK", flush=True)
os._exit(0)
