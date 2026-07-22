"""橋梁リスク可視化ダッシュボード（初心者向けシンプル版）

地図上で、橋梁データを属性（クラスター・道路種別）で絞り込んだり、
特定の橋を選んで表示したりできる、Streamlitアプリです。
"""
import os
import tempfile

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

st.set_page_config(page_title="橋梁リスク可視化ダッシュボード", layout="wide")

# ---------------------------------------------------------------------------
# クラスター・道路種別を分かりやすい日本語ラベルに変換するための対応表
# （03_eda_clustering.ipynb でのクラスター解釈まとめに基づく）
# ---------------------------------------------------------------------------
CLUSTER_LABELS = {
    0: "0: 標準橋群（橋長20m程度）",
    1: "1: 交通集中×長距離迂回",
    2: "2: 超長大橋",
    3: "3: 標準橋群（橋長20〜100m程度・幹線）",
    4: "4: 高交通需要",
    5: "5: 老朽化進行",
}
CLUSTER_COLORS = {
    0: "#4C72B0", 1: "#DD8452", 2: "#55A868",
    3: "#C44E52", 4: "#8172B2", 5: "#937860",
}
HIGHWAY_LABELS = {
    1: "1: 主要道",
    2: "2: 二次主要道",
    3: "3: 一般道路",
    4: "4: 補助道路",
    5: "5: 生活道路",
}
QUADRANT_LABELS = {
    1: "左下：交通量少 × 迂回路短",
    2: "左上：交通量少 × 迂回路長",
    3: "右下：交通量多 × 迂回路短",
    4: "右上：交通量多 × 迂回路長（優先度高）",
}

DEFAULT_DATA_PATHS = [
    "../data/processed/final_analysis_gdf.gpkg",
    "data/processed/final_analysis_gdf.gpkg",
    "final_analysis_gdf.gpkg",
]


@st.cache_data(show_spinner="データを読み込んでいます...")
def load_data(file_source) -> pd.DataFrame:
    """GeoPackageを読み込み、緯度経度付きの通常のDataFrameとして返す。

    Args:
        file_source: ファイルパス（str）、またはst.file_uploaderから受け取ったファイルオブジェクト

    Returns:
        lat, lon列を持つDataFrame（クラスター等のラベル列も付与済み）
    """
    # GeoPackageはSQLiteベースの形式で、アップロードされたファイルオブジェクト(メモリ上のバイト列)を
    # 直接は読み込めないことがあるため、一時ファイルに保存してから読み込む
    if isinstance(file_source, str):
        gdf = gpd.read_file(file_source)
    else:
        with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp_file:
            tmp_file.write(file_source.getbuffer())
            tmp_path = tmp_file.name
        gdf = gpd.read_file(tmp_path)
        os.remove(tmp_path)

    gdf = gdf.to_crs(epsg=4326)  # 地図表示用に緯度経度(WGS84)へ変換
    gdf["lat"] = gdf.geometry.y
    gdf["lon"] = gdf.geometry.x

    df = pd.DataFrame(gdf.drop(columns="geometry"))
    df["cluster_label_ja"] = df["cluster_6_label"].map(CLUSTER_LABELS)
    df["highway_label_ja"] = df["osm_highway_aggregated"].map(HIGHWAY_LABELS)
    df["quadrant_label_ja"] = df["traffic_detour_quadrant"].map(QUADRANT_LABELS)
    return df


def find_default_data_path():
    for path in DEFAULT_DATA_PATHS:
        if os.path.exists(path):
            return path
    return None


# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------
st.title("🌉 橋梁リスク可視化ダッシュボード")
st.caption("東京23区の橋梁データを、地図上で属性ごとに絞り込んで確認できます。")

default_path = find_default_data_path()

if default_path is not None:
    df = load_data(default_path)
else:
    st.warning(
        "既定の場所（`data/processed/final_analysis_gdf.gpkg`）にデータが見つかりませんでした。"
        " 下のボタンから `final_analysis_gdf.gpkg` をアップロードしてください。"
    )
    uploaded_file = st.file_uploader("final_analysis_gdf.gpkg をアップロード", type=["gpkg"])
    if uploaded_file is None:
        st.stop()
    df = load_data(uploaded_file)

# ---------------------------------------------------------------------------
# サイドバー：絞り込み条件
# ---------------------------------------------------------------------------
st.sidebar.header("🔍 絞り込み条件")

selected_clusters = st.sidebar.multiselect(
    "クラスター（橋の特徴グループ）",
    options=sorted(df["cluster_6_label"].unique()),
    default=sorted(df["cluster_6_label"].unique()),
    format_func=lambda x: CLUSTER_LABELS.get(x, str(x)),
)

selected_highways = st.sidebar.multiselect(
    "道路種別",
    options=sorted(df["osm_highway_aggregated"].unique()),
    default=sorted(df["osm_highway_aggregated"].unique()),
    format_func=lambda x: HIGHWAY_LABELS.get(x, str(x)),
)

only_high_priority = st.sidebar.checkbox(
    "優先度が高い橋（総合優先度スコア 上位30件）のみ表示", value=False
)

st.sidebar.markdown("---")
bridge_names = ["（指定しない）"] + sorted(df["bridge_name"].unique().tolist())
selected_bridge = st.sidebar.selectbox("特定の橋を検索して表示", bridge_names)

# ---------------------------------------------------------------------------
# 絞り込み処理
# ---------------------------------------------------------------------------
filtered_df = df[
    df["cluster_6_label"].isin(selected_clusters)
    & df["osm_highway_aggregated"].isin(selected_highways)
].copy()

if only_high_priority:
    filtered_df = filtered_df.sort_values("overall_rank").head(30)

if selected_bridge != "（指定しない）":
    filtered_df = filtered_df[filtered_df["bridge_name"] == selected_bridge]

st.write(f"**表示件数：{len(filtered_df)} 件** / 全{len(df)}件")

# ---------------------------------------------------------------------------
# 地図表示
# ---------------------------------------------------------------------------
if len(filtered_df) == 0:
    st.info("条件に一致する橋がありません。絞り込み条件を変更してください。")
else:
    if selected_bridge != "（指定しない）":
        map_center = [filtered_df["lat"].iloc[0], filtered_df["lon"].iloc[0]]
        zoom_start = 16
    else:
        map_center = [filtered_df["lat"].mean(), filtered_df["lon"].mean()]
        zoom_start = 11

    m = folium.Map(location=map_center, zoom_start=zoom_start, tiles="OpenStreetMap")
    marker_cluster = MarkerCluster().add_to(m)

    for _, row in filtered_df.iterrows():
        popup_html = f"""
        <b>{row['bridge_name']}</b><br>
        架設年度: {row['dpf_kasetsu_nendo']}年<br>
        幅員: {row['dpf_fukuin']:.1f}m / 橋長: {row['dpf_kyouchou']:.1f}m<br>
        交通量: {row['traffic_count_24h_auto']:.0f}台/日<br>
        迂回路長: {row['detour_length_m']:.0f}m<br>
        分類: {row['cluster_label_ja']}<br>
        交通量×迂回路: {row['quadrant_label_ja']}<br>
        優先度順位: {int(row['overall_rank'])}位 / {len(df)}件中
        """
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=6,
            color=CLUSTER_COLORS.get(row["cluster_6_label"], "#333333"),
            fill=True,
            fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=row["bridge_name"],
        ).add_to(marker_cluster)

    st.subheader("地図")
    st.caption("マーカーの色はクラスター（橋の特徴グループ）を表します。クリックすると詳細が表示されます。")
    st_folium(m, width=1100, height=600, returned_objects=[])

    with st.expander("凡例：マーカーの色とクラスターの対応"):
        for cid, label in CLUSTER_LABELS.items():
            st.markdown(
                f"<span style='color:{CLUSTER_COLORS[cid]}; font-size:20px;'>●</span> {label}",
                unsafe_allow_html=True,
            )

    # -----------------------------------------------------------------
    # 一覧表
    # -----------------------------------------------------------------
    st.subheader("一覧表")
    display_cols = {
        "bridge_name": "橋梁名",
        "dpf_kasetsu_nendo": "架設年度",
        "dpf_fukuin": "幅員(m)",
        "dpf_kyouchou": "橋長(m)",
        "traffic_count_24h_auto": "交通量(台/日)",
        "detour_length_m": "迂回路長(m)",
        "cluster_label_ja": "クラスター",
        "overall_rank": "優先度順位",
    }
    table_df = (
        filtered_df[list(display_cols.keys())]
        .rename(columns=display_cols)
        .sort_values("優先度順位")
        .reset_index(drop=True)
    )
    st.dataframe(table_df, use_container_width=True)
