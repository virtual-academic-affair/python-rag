from __future__ import annotations
import logging
from app.modules.rag.corpus.repositories.corpus_node_repository import CorpusNodeRepository

logger = logging.getLogger(__name__)

# (slug, title, summary, parent_slug) — slug chính là node_key (mọi node đều là topic).
# parent_slug=None → topic gốc (tầng 1 của cây).
# parent_slug="x"  → con của node "x" (cha phải khai báo TRƯỚC con trong list).
SEED_TOPICS: list[tuple[str, str, str, str | None]] = [
    # ── Topic gốc (tầng 1) ────────────────────────────────────────────
    ("chuan-dau-ra",          "Chuẩn đầu ra",                    "Các chuẩn đầu ra bắt buộc để tốt nghiệp: ngoại ngữ, tin học, chuẩn chương trình", None),
    ("tot-nghiep",            "Tốt nghiệp & văn bằng",           "Điều kiện tốt nghiệp, xét tốt nghiệp, đồ án, văn bằng chứng chỉ", None),
    ("to-chuc-dao-tao",       "Tổ chức đào tạo & học tập",       "Chương trình đào tạo, đăng ký học phần, thời khóa biểu, lớp học phần", None),
    ("thi-cu-diem-so",        "Thi cử & điểm số",                "Lịch thi, kết quả học tập, bảng điểm, phúc khảo", None),
    ("tai-chinh-ho-tro",      "Học phí, học bổng & hỗ trợ",      "Học phí, miễn giảm, các loại học bổng và chính sách hỗ trợ", None),
    ("hoc-vu-sinh-vien",      "Học vụ & hành chính sinh viên",   "Cảnh báo học vụ, nghỉ học bảo lưu, chuyển ngành, quy chế sinh viên", None),

    # ── Topic con (tầng 2) ────────────────────────────────────────────
    ("chuan-dau-ra-ngoai-ngu",    "Chuẩn đầu ra ngoại ngữ",            "Quy định về chuẩn đầu ra ngoại ngữ bắt buộc để tốt nghiệp", "chuan-dau-ra"),
    ("chuan-dau-ra-tin-hoc",      "Chuẩn đầu ra tin học",               "Quy định về chuẩn đầu ra tin học bắt buộc để tốt nghiệp", "chuan-dau-ra"),
    ("dieu-kien-tot-nghiep",      "Điều kiện tốt nghiệp",               "Các điều kiện cần đáp ứng để được xét tốt nghiệp", "tot-nghiep"),
    ("xet-tot-nghiep",            "Xét tốt nghiệp & cấp bằng",          "Quy trình xét tốt nghiệp, cấp phát và công nhận bằng tốt nghiệp", "tot-nghiep"),
    ("thuc-tap-do-an",            "Thực tập & đồ án tốt nghiệp",        "Quy định thực tập tốt nghiệp và thực hiện đồ án", "tot-nghiep"),
    ("van-bang-chung-chi",        "Văn bằng & chứng chỉ",               "Cấp phát, xác nhận văn bằng và các loại chứng chỉ", "tot-nghiep"),
    ("chuong-trinh-dao-tao",      "Chương trình đào tạo",               "Cấu trúc chương trình, học phần bắt buộc và tự chọn", "to-chuc-dao-tao"),
    ("dang-ky-hoc-phan",          "Đăng ký học phần",                   "Thủ tục, thời gian và điều kiện đăng ký học phần", "to-chuc-dao-tao"),
    ("thoi-khoa-bieu",            "Thời khoá biểu & lịch học",          "Thời khóa biểu, lịch thi và các mốc học kỳ", "to-chuc-dao-tao"),
    ("lop-hoc-phan-nhom-hoc",     "Lớp học phần & nhóm học",            "Mở lớp, ghép nhóm và quy định sĩ số lớp học phần", "to-chuc-dao-tao"),
    ("hoc-lai-hoc-cai-thien",     "Học lại, học cải thiện điểm",        "Quy định học lại và đăng ký học cải thiện điểm", "to-chuc-dao-tao"),
    ("thi-cu-kiem-tra",           "Thi cử & kiểm tra",                   "Lịch thi, hình thức thi và quy định phòng thi", "thi-cu-diem-so"),
    ("ket-qua-hoc-tap",           "Kết quả học tập & bảng điểm",        "Tra cứu điểm, bảng điểm và kết quả học tập", "thi-cu-diem-so"),
    ("phuc-khao-diem",            "Phúc khảo & phúc tra điểm",          "Thủ tục phúc khảo, phúc tra điểm thi", "thi-cu-diem-so"),
    ("hoc-phi-mien-giam",         "Học phí & miễn giảm",                "Mức học phí, thời hạn đóng và chính sách miễn giảm", "tai-chinh-ho-tro"),
    ("hoc-bong",                  "Học bổng",                           "Các loại học bổng, điều kiện xét và thủ tục đăng ký", "tai-chinh-ho-tro"),
    ("canh-bao-hoc-vu",           "Cảnh báo học vụ",                    "Quy định cảnh báo học vụ và xử lý sinh viên yếu kém", "hoc-vu-sinh-vien"),
    ("buoi-hoc-nghi-hoc",         "Nghỉ học, bảo lưu, thôi học",        "Thủ tục nghỉ học có phép, bảo lưu và thôi học", "hoc-vu-sinh-vien"),
    ("chuyen-nganh-chuyen-truong", "Chuyển ngành, chuyển trường",       "Điều kiện và thủ tục chuyển ngành, chuyển trường", "hoc-vu-sinh-vien"),
    ("quy-che-sinh-vien",         "Quy chế sinh viên",                   "Quyền và nghĩa vụ sinh viên, khen thưởng và kỷ luật", "hoc-vu-sinh-vien"),
]


async def seed_corpus(repo: CorpusNodeRepository) -> int:
    """Seed cây topic. Idempotent — node đã tồn tại thì bỏ qua."""
    created = 0
    for slug, title, summary, parent_slug in SEED_TOPICS:
        if await repo.get_by_key(slug):
            continue
        await repo.upsert_node(
            slug,
            title=title,
            summary=summary,
            parent_key=parent_slug,
        )
        created += 1

    logger.info(f"[Corpus] seed_corpus: tạo {created} topic node")
    return created
