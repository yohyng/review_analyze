"""Generate faithful sample files for testing the importers.

  python samples/make_sample.py

Produces:
  samples/sample_reviews.csv  (tab-separated, mimics the real KAIZODE export:
                               blank place_name, multi-line quoted review,
                               Python-literal review_details, misspelled header)
  samples/sample_scores.xlsx  (wide layout: 施設名 + 独自指標列)
"""
import csv
from pathlib import Path

from openpyxl import Workbook

HERE = Path(__file__).resolve().parent

COLUMNS = [
    "timestamp", "input", "error", "error_code", "url", "place_id", "place_name",
    "country", "address", "review_id", "reviewer_name", "reviews_by_reviewer",
    "photos_by_reviewer", "reviewer_url", "local_guide", "review_rating", "review",
    "review_date", "number_of_likes", "response_of_owner", "response_date", "photos",
    "review_details", "profile_pic_url", "place_general_rating",
    "overall_place_riviews",  # NOTE: misspelled in the real export
    "questions_answers", "fid_location", "category", "cid",
]

REVIEW_1 = (
    "線状降水帯で避難勧告の出ている中、両親の米寿で愛知県からの訪問でした。\n"
    "子供の頃はマリンランドと言う名称でアイススケートリンクもあり良く利用した所だったのですが、全く変わっていました。\n"
    "とても素敵なホテルで天気が良ければ景色も最高だろうと思います。\n"
    "大浴場はなく、全室個室風呂ですが外を眺めて入浴出来ます。ただ、ガラス扉から水が脱衣所に漏れるのが気になりました。\n"
    "食事はフグのテッサやローストビーフが最高でお酒もすすみました。\n"
    "米寿の祝いを伝えると料理長が特別に寿の彫物をした赤カブを備えてシャンパンのサービスも頂きました。\n"
    "機会があれば天気の良い時に再訪問したいです。\n"
    "お世話になりました。"
)
REVIEW_2 = "部屋からの眺めは良かったですが、食事の提供が少し遅かったです。\n接客は丁寧でした。"

ROWS = [
    {
        "timestamp": "2025-11-04T06:48:40.604Z",
        "input": "{'url': 'https://www.google.com/maps/search/?api=1&query="
                 "%E9%A2%A8%E3%81%AE%E6%B5%B7%20%E5%B1%B1%E5%8F%A3%E7%9C%8C', "
                 "'days_limit': 1825}",
        "url": "https://www.google.com/maps/search/?api=1&query=%E9%A2%A8%E3%81%AE%E6%B5%B7",
        "place_name": "",  # intentionally blank, like the real data
        "review_id": "Ci9DQUlRQUNvZENodHljRjlvT2pOdFRERldOazVRT1ZOeVpGQkpObEZvWXpSb1NYYxAB",
        "reviewer_name": "政章（夕焼）",
        "reviews_by_reviewer": "11",
        "photos_by_reviewer": "13",
        "reviewer_url": "https://www.google.com/maps/contrib/111720807864853443484/reviews?hl=en",
        "local_guide": "TRUE",
        "review_rating": "5",
        "review": REVIEW_1,
        "review_date": "2025-08-11T14:30:05.419Z",
        "number_of_likes": "0",
        "photos": "['https://lh3.googleusercontent.com/a', 'https://lh3.googleusercontent.com/b']",
        "review_details": "[{'title': 'Rooms', 'value': '5'}, {'title': 'Service', 'value': '5'}, "
                          "{'title': 'Location', 'value': '5'}]",
        "place_general_rating": "4.5",
        "overall_place_riviews": "240",
    },
    {
        "timestamp": "2025-11-04T06:48:41.604Z",
        "input": "{'url': 'https://www.google.com/maps/search/?api=1&query=%E9%A2%A8', 'days_limit': 1825}",
        "review_id": "Ci9DU0FNUExFMDAwMl9zZWNvbmRfcmV2aWV3X2lkX3Rlc3RfMDIudGVzdBAB",
        "reviewer_name": "田中 花子",
        "reviews_by_reviewer": "3",
        "local_guide": "FALSE",
        "review_rating": "3",
        "review": REVIEW_2,
        "review_date": "2025-07-02T09:12:00.000Z",
        "number_of_likes": "1",
        "review_details": "[{'title': 'Service', 'value': '4'}]",
        "place_general_rating": "4.5",
        "overall_place_riviews": "240",
    },
]


def make_reviews_csv() -> Path:
    path = HERE / "sample_reviews.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter="\t", restval="")
        w.writeheader()
        w.writerows(ROWS)
    return path


def make_scores_xlsx() -> Path:
    path = HERE / "sample_scores.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "scores"
    ws.append(["施設名", "清潔感", "スタッフ対応", "食事", "設備", "立地"])
    ws.append(["風の海", 4.2, 4.6, 3.9, 3.5, 4.8])
    ws.append(["海の宿 潮", 3.8, 3.5, 4.1, 3.9, 3.2])
    wb.save(path)
    return path


if __name__ == "__main__":
    print("wrote", make_reviews_csv())
    print("wrote", make_scores_xlsx())
