from __future__ import annotations
import logging
from app.modules.corpus.models.corpus_node import NodeType
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository

logger = logging.getLogger(__name__)

ROOT_AND_AXES = [
    {"node_key": "root", "title": "Corpus", "summary": "Gốc kho dữ liệu", "parent": None},
    {"node_key": "axis:documents", "title": "Tài liệu", "summary": "Trục tài liệu", "parent": "root"},
    {"node_key": "axis:faqs", "title": "FAQ", "summary": "Trục FAQ", "parent": "root"},
    {"node_key": "axis:topics", "title": "Chủ đề", "summary": "Trục chủ đề", "parent": "root"},
    {"node_key": "axis:document_types", "title": "Loại văn bản", "summary": "Trục loại văn bản", "parent": "root"},
    {"node_key": "axis:enrollment_years", "title": "Khóa tuyển sinh", "summary": "Trục khóa", "parent": "root"},
    {"node_key": "axis:academic_years", "title": "Năm học", "summary": "Trục năm học", "parent": "root"},
]

# (slug, title, summary) — slug becomes node_key "topic:<slug>"
SEED_TOPICS: list[tuple[str, str, str]] = [
    ("chuan-dau-ra-ngoai-ngu",    "Chuẩn đầu ra ngoại ngữ",            "Quy định về chuẩn đầu ra ngoại ngữ bắt buộc để tốt nghiệp"),
    ("chuan-dau-ra-tin-hoc",      "Chuẩn đầu ra tin học",               "Quy định về chuẩn đầu ra tin học bắt buộc để tốt nghiệp"),
    ("dieu-kien-tot-nghiep",      "Điều kiện tốt nghiệp",               "Các điều kiện cần đáp ứng để được xét tốt nghiệp"),
    ("xet-tot-nghiep",            "Xét tốt nghiệp & cấp bằng",          "Quy trình xét tốt nghiệp, cấp phát và công nhận bằng tốt nghiệp"),
    ("chuong-trinh-dao-tao",      "Chương trình đào tạo",               "Cấu trúc chương trình, học phần bắt buộc và tự chọn"),
    ("dang-ky-hoc-phan",          "Đăng ký học phần",                   "Thủ tục, thời gian và điều kiện đăng ký học phần"),
    ("thoi-khoa-bieu",            "Thời khoá biểu & lịch học",          "Thời khóa biểu, lịch thi và các mốc học kỳ"),
    ("ket-qua-hoc-tap",           "Kết quả học tập & bảng điểm",        "Tra cứu điểm, bảng điểm và kết quả học tập"),
    ("canh-bao-hoc-vu",           "Cảnh báo học vụ",                    "Quy định cảnh báo học vụ và xử lý sinh viên yếu kém"),
    ("buoi-hoc-nghi-hoc",         "Nghỉ học, bảo lưu, thôi học",        "Thủ tục nghỉ học có phép, bảo lưu và thôi học"),
    ("chuyen-nganh-chuyen-truong", "Chuyển ngành, chuyển trường",       "Điều kiện và thủ tục chuyển ngành, chuyển trường"),
    ("hoc-phi-mien-giam",         "Học phí & miễn giảm",                "Mức học phí, thời hạn đóng và chính sách miễn giảm"),
    ("hoc-bong",                  "Học bổng",                           "Các loại học bổng, điều kiện xét và thủ tục đăng ký"),
    ("thuc-tap-do-an",            "Thực tập & đồ án tốt nghiệp",        "Quy định thực tập tốt nghiệp và thực hiện đồ án"),
    ("lop-hoc-phan-nhom-hoc",     "Lớp học phần & nhóm học",            "Mở lớp, ghép nhóm và quy định sĩ số lớp học phần"),
    ("thi-cu-kiem-tra",           "Thi cử & kiểm tra",                   "Lịch thi, hình thức thi và quy định phòng thi"),
    ("phuc-khao-diem",            "Phúc khảo & phúc tra điểm",          "Thủ tục phúc khảo, phúc tra điểm thi"),
    ("hoc-lai-hoc-cai-thien",     "Học lại, học cải thiện điểm",        "Quy định học lại và đăng ký học cải thiện điểm"),
    ("van-bang-chung-chi",        "Văn bằng & chứng chỉ",               "Cấp phát, xác nhận văn bằng và các loại chứng chỉ"),
    ("quy-che-sinh-vien",         "Quy chế sinh viên",                   "Quyền và nghĩa vụ sinh viên, khen thưởng và kỷ luật"),
]


async def seed_corpus(repo: CorpusNodeRepository) -> int:
    created = 0

    # Root + axes
    for n in ROOT_AND_AXES:
        if await repo.get_by_key(n["node_key"]):
            continue
        ntype = NodeType.ROOT if n["node_key"] == "root" else NodeType.AXIS
        await repo.upsert_node(
            n["node_key"],
            node_type=ntype,
            title=n["title"],
            summary=n["summary"],
            axis_parent_key=n["parent"],
        )
        created += 1

    # Topics
    for slug, title, summary in SEED_TOPICS:
        node_key = f"topic:{slug}"
        if await repo.get_by_key(node_key):
            continue
        await repo.upsert_node(
            node_key,
            node_type=NodeType.TOPIC,
            title=title,
            summary=summary,
            axis_parent_key="axis:topics",
        )
        created += 1

    logger.info(f"[Corpus] seed_corpus: tạo {created} node (root/axis/topic)")
    return created
