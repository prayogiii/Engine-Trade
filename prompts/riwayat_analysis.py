"""Prompt untuk analisis riwayat global (analisis_riwayat_global)."""

RIWAYAT_ANALYSIS_SUFFIX = (
    "\nBerdasarkan data di atas, berikan analisis ringkas (Bahasa Indonesia):\n"
    "- Pola sinyal yang sering muncul\n"
    "- Saham dengan peluang terbaik menurut data (termasuk hasil aktualnya)\n"
    "- Rekomendasi perbaikan strategi\n"
    "- Insight tambahan yang berguna untuk trader\n"
)


def build_riwayat_header() -> str:
    return "Berikut adalah riwayat analisis saham yang telah dilakukan (termasuk hasil aktual jika tersedia):\n\n"