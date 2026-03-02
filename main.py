#!/usr/bin/env python3
"""
Bot Telegram - Inventory Pembelian Bahan Baku
Terhubung ke Google Sheets
"""

import logging
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)
import gspread
from google.oauth2.service_account import Credentials
import json

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Config dari Environment Variables ───────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]  # JSON string

# ─── Conversation States ──────────────────────────────────────────────────────
(
    MENU,
    BELI_CARI, BELI_PILIH, BELI_JUMLAH, BELI_SATUAN, BELI_HARGA_MANUAL, BELI_KONFIRMASI,
    TAMBAH_NAMA, TAMBAH_SATUAN, TAMBAH_HARGA_SAK, TAMBAH_ISI_SAK, TAMBAH_KONFIRMASI,
    CEK_NAMA,
) = range(13)

# ─── Google Sheets ────────────────────────────────────────────────────────────
def get_gspread_client():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

def get_or_create_sheet(name: str, headers: list):
    client = get_gspread_client()
    ss = client.open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=1000, cols=20)
        ws.append_row(headers)
    return ws

def sheet_database():
    return get_or_create_sheet(
        "Database Bahan Baku",
        ["ID", "Nama Bahan", "Satuan Terkecil", "Harga/Sak (Rp)", "Isi per Sak", "Harga per Satuan Terkecil", "Tanggal Ditambah"]
    )

def sheet_riwayat():
    return get_or_create_sheet(
        "Riwayat Pembelian",
        ["Tanggal", "Nama Bahan", "Jumlah", "Satuan", "Harga Satuan (Rp)", "Total (Rp)", "Catatan"]
    )

# ─── DB Functions ─────────────────────────────────────────────────────────────
def get_all_bahan():
    return sheet_database().get_all_records()

def cari_bahan(keyword: str):
    keyword = keyword.lower()
    return [b for b in get_all_bahan() if keyword in b.get("Nama Bahan", "").lower()]

def tambah_bahan(nama, satuan, harga_sak, isi_sak):
    ws = sheet_database()
    existing = ws.get_all_records()
    new_id = len(existing) + 1
    harga_satuan = round(harga_sak / isi_sak, 4) if isi_sak > 0 else 0
    tanggal = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([new_id, nama, satuan, harga_sak, isi_sak, harga_satuan, tanggal])
    return new_id, harga_satuan

def catat_pembelian(nama, jumlah, satuan, harga_satuan, catatan=""):
    ws = sheet_riwayat()
    tanggal = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = round(jumlah * harga_satuan, 2)
    ws.append_row([tanggal, nama, jumlah, satuan, harga_satuan, total, catatan])
    return total

def get_riwayat(limit=10):
    records = sheet_riwayat().get_all_records()
    return records[-limit:]

def get_rekap_bulan(bulan: str):
    records = sheet_riwayat().get_all_records()
    filtered = [r for r in records if str(r.get("Tanggal", "")).startswith(bulan)]
    total = sum(r.get("Total (Rp)", 0) for r in filtered)
    return filtered, total

# ─── Helpers ──────────────────────────────────────────────────────────────────
def fmt_rp(angka):
    try:
        return f"Rp {int(float(angka)):,}".replace(",", ".")
    except:
        return f"Rp {angka}"

def parse_angka(text: str):
    text = text.strip().replace("rp", "").replace("Rp", "").replace("RP", "")
    text = text.replace(" ", "")
    # Deteksi format: jika ada koma sebelum 3 digit terakhir → ribuan pakai koma
    if "," in text and "." in text:
        # Ambil yg lebih masuk akal: 1.000,5 → 1000.5
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        # bisa 1,5 (desimal) atau 1,000 (ribuan)
        parts = text.split(",")
        if len(parts[-1]) == 3:
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    elif "." in text:
        parts = text.split(".")
        if len(parts[-1]) == 3:
            text = text.replace(".", "")
    return float(text)

def back_button():
    return [[InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]]

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Catat Pembelian", callback_data="menu_beli")],
        [InlineKeyboardButton("➕ Tambah Bahan Baru", callback_data="menu_tambah")],
        [InlineKeyboardButton("🔍 Cek Harga Bahan", callback_data="menu_cek")],
        [InlineKeyboardButton("📋 Riwayat Pembelian", callback_data="menu_riwayat")],
        [InlineKeyboardButton("📊 Rekap Pengeluaran", callback_data="menu_rekap")],
    ])

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nama = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Halo *{nama}*!\n\n"
        "🏭 *Bot Inventory Bahan Baku*\n"
        "Pilih menu di bawah ini:",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    return MENU

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📦 *Menu Utama* — pilih aksi:",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    return MENU

# ─── CATAT PEMBELIAN ──────────────────────────────────────────────────────────
async def menu_beli(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🛒 *Catat Pembelian*\n\n"
        "Ketik nama bahan baku yang dibeli:\n"
        "_(contoh: gula, tepung terigu)_",
        parse_mode="Markdown"
    )
    return BELI_CARI

async def beli_cari(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.strip()
    hasil = cari_bahan(keyword)

    if not hasil:
        await update.message.reply_text(
            f"❌ Bahan *{keyword}* tidak ditemukan di database.\n\n"
            "Mau tambahkan sebagai bahan baru?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Tambah bahan baru", callback_data=f"beli_tambah_baru:{keyword}")],
                [InlineKeyboardButton("🔙 Cari lagi", callback_data="menu_beli")],
                [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")],
            ])
        )
        return MENU

    context.user_data['beli_hasil'] = hasil
    buttons = [
        [InlineKeyboardButton(
            f"📦 {b['Nama Bahan']} ({b['Satuan Terkecil']})",
            callback_data=f"beli_pilih:{i}"
        )]
        for i, b in enumerate(hasil)
    ]
    buttons.append([InlineKeyboardButton("🔙 Cari lagi", callback_data="menu_beli")])

    await update.message.reply_text(
        f"✅ Ditemukan *{len(hasil)}* bahan. Pilih:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return BELI_PILIH

async def beli_pilih(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":")[1])
    bahan = context.user_data['beli_hasil'][idx]
    context.user_data['beli_bahan'] = bahan

    await query.edit_message_text(
        f"📦 *{bahan['Nama Bahan']}*\n"
        f"• Harga/sak: {fmt_rp(bahan['Harga/Sak (Rp)'])} ({bahan['Isi per Sak']} {bahan['Satuan Terkecil']})\n"
        f"• Harga/{bahan['Satuan Terkecil']}: {fmt_rp(bahan['Harga per Satuan Terkecil'])}\n\n"
        "Masukkan *jumlah* yang dibeli (angka):\n"
        "_(contoh: 5 atau 2.5)_",
        parse_mode="Markdown"
    )
    return BELI_JUMLAH

async def beli_jumlah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        jumlah = parse_angka(update.message.text)
        if jumlah <= 0:
            raise ValueError
        context.user_data['beli_jumlah'] = jumlah
    except:
        await update.message.reply_text("❌ Masukkan angka yang valid, contoh: *5* atau *2.5*", parse_mode="Markdown")
        return BELI_JUMLAH

    bahan = context.user_data['beli_bahan']
    await update.message.reply_text(
        f"Pilih satuan untuk *{jumlah}* yang dibeli:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{bahan['Satuan Terkecil']} → {fmt_rp(bahan['Harga per Satuan Terkecil'])}/{bahan['Satuan Terkecil']}",
                callback_data=f"beli_satuan:{bahan['Satuan Terkecil']}:{bahan['Harga per Satuan Terkecil']}"
            )],
            [InlineKeyboardButton(
                f"Sak ({bahan['Isi per Sak']} {bahan['Satuan Terkecil']}) → {fmt_rp(bahan['Harga/Sak (Rp)'])}/sak",
                callback_data=f"beli_satuan:sak:{bahan['Harga/Sak (Rp)']}"
            )],
            [InlineKeyboardButton("✏️ Input harga manual", callback_data="beli_satuan:manual:0")],
        ])
    )
    return BELI_SATUAN

async def beli_satuan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, satuan, harga_str = query.data.split(":", 2)
    context.user_data['beli_satuan'] = satuan

    if satuan == "manual":
        await query.edit_message_text(
            "💰 Ketik *harga per satuan* (Rp):\n_(contoh: 15000)_",
            parse_mode="Markdown"
        )
        return BELI_HARGA_MANUAL

    context.user_data['beli_harga'] = float(harga_str)
    return await _tampil_konfirmasi_beli(query, context)

async def beli_harga_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        harga = parse_angka(update.message.text)
        if harga <= 0:
            raise ValueError
        context.user_data['beli_harga'] = harga
    except:
        await update.message.reply_text("❌ Masukkan angka valid, contoh: *15000*", parse_mode="Markdown")
        return BELI_HARGA_MANUAL

    bahan = context.user_data['beli_bahan']
    jumlah = context.user_data['beli_jumlah']
    satuan = context.user_data.get('beli_satuan', bahan['Satuan Terkecil'])
    total = jumlah * harga

    await update.message.reply_text(
        f"📋 *Konfirmasi Pembelian*\n\n"
        f"• Bahan: {bahan['Nama Bahan']}\n"
        f"• Jumlah: {jumlah} {satuan}\n"
        f"• Harga/{satuan}: {fmt_rp(harga)}\n"
        f"• *Total: {fmt_rp(total)}*\n\n"
        "Simpan?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ya, simpan", callback_data="beli_simpan")],
            [InlineKeyboardButton("❌ Batal", callback_data="main_menu")],
        ])
    )
    return BELI_KONFIRMASI

async def _tampil_konfirmasi_beli(query, context):
    bahan = context.user_data['beli_bahan']
    jumlah = context.user_data['beli_jumlah']
    satuan = context.user_data['beli_satuan']
    harga = context.user_data['beli_harga']
    total = jumlah * harga

    await query.edit_message_text(
        f"📋 *Konfirmasi Pembelian*\n\n"
        f"• Bahan: {bahan['Nama Bahan']}\n"
        f"• Jumlah: {jumlah} {satuan}\n"
        f"• Harga/{satuan}: {fmt_rp(harga)}\n"
        f"• *Total: {fmt_rp(total)}*\n\n"
        "Simpan?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ya, simpan", callback_data="beli_simpan")],
            [InlineKeyboardButton("❌ Batal", callback_data="main_menu")],
        ])
    )
    return BELI_KONFIRMASI

async def beli_simpan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Menyimpan...")
    d = context.user_data
    total = catat_pembelian(
        d['beli_bahan']['Nama Bahan'],
        d['beli_jumlah'],
        d['beli_satuan'],
        d['beli_harga']
    )
    await query.edit_message_text(
        f"✅ *Pembelian berhasil dicatat!*\n\n"
        f"📦 {d['beli_bahan']['Nama Bahan']} — {d['beli_jumlah']} {d['beli_satuan']}\n"
        f"💰 Total: *{fmt_rp(total)}*\n\n"
        f"_Tersimpan di Google Sheets_ ✓",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(back_button())
    )
    return MENU

# ─── TAMBAH BAHAN BARU ────────────────────────────────────────────────────────
async def menu_tambah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "➕ *Tambah Bahan Baru*\n\nKetik *nama bahan baku* baru:",
        parse_mode="Markdown"
    )
    return TAMBAH_NAMA

async def tambah_dari_beli(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nama = query.data.split(":", 1)[1]
    context.user_data['tambah_nama'] = nama.title()
    await query.edit_message_text(
        f"➕ Tambah *{nama.title()}* ke database\n\n"
        "Ketik *satuan terkecil*:\n_(contoh: gram, ml, liter, pcs, kg)_",
        parse_mode="Markdown"
    )
    return TAMBAH_SATUAN

async def tambah_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nama = update.message.text.strip().title()
    existing = cari_bahan(nama)
    context.user_data['tambah_nama'] = nama

    peringatan = ""
    if existing:
        peringatan = f"⚠️ _{nama}_ sudah ada di database, tapi tetap bisa ditambah.\n\n"

    await update.message.reply_text(
        f"{peringatan}✅ Nama: *{nama}*\n\n"
        "Ketik *satuan terkecil*:\n_(contoh: gram, ml, liter, pcs, kg)_",
        parse_mode="Markdown"
    )
    return TAMBAH_SATUAN

async def tambah_satuan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    satuan = update.message.text.strip().lower()
    context.user_data['tambah_satuan'] = satuan
    await update.message.reply_text(
        f"✅ Satuan: *{satuan}*\n\n"
        "Masukkan *harga per sak/kemasan* (Rp):",
        parse_mode="Markdown"
    )
    return TAMBAH_HARGA_SAK

async def tambah_harga_sak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        harga = parse_angka(update.message.text)
        if harga <= 0:
            raise ValueError
        context.user_data['tambah_harga_sak'] = harga
    except:
        await update.message.reply_text("❌ Masukkan angka valid, contoh: *50000*", parse_mode="Markdown")
        return TAMBAH_HARGA_SAK

    satuan = context.user_data['tambah_satuan']
    await update.message.reply_text(
        f"✅ Harga/sak: *{fmt_rp(harga)}*\n\n"
        f"Berapa *isi per sak* dalam {satuan}?\n"
        f"_(contoh: 1000 artinya 1 sak = 1000 {satuan})_",
        parse_mode="Markdown"
    )
    return TAMBAH_ISI_SAK

async def tambah_isi_sak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        isi = parse_angka(update.message.text)
        if isi <= 0:
            raise ValueError
        context.user_data['tambah_isi_sak'] = isi
    except:
        await update.message.reply_text("❌ Masukkan angka valid", parse_mode="Markdown")
        return TAMBAH_ISI_SAK

    d = context.user_data
    harga_satuan = round(d['tambah_harga_sak'] / isi, 4)

    await update.message.reply_text(
        f"📋 *Konfirmasi Data Bahan Baru*\n\n"
        f"• Nama: *{d['tambah_nama']}*\n"
        f"• Satuan terkecil: {d['tambah_satuan']}\n"
        f"• Harga/sak: {fmt_rp(d['tambah_harga_sak'])}\n"
        f"• Isi/sak: {isi} {d['tambah_satuan']}\n"
        f"• Harga/{d['tambah_satuan']}: *{fmt_rp(harga_satuan)}*\n\n"
        "Simpan ke database?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Simpan", callback_data="tambah_simpan")],
            [InlineKeyboardButton("❌ Batal", callback_data="main_menu")],
        ])
    )
    return TAMBAH_KONFIRMASI

async def tambah_simpan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Menyimpan...")
    d = context.user_data
    new_id, harga_satuan = tambah_bahan(
        d['tambah_nama'], d['tambah_satuan'], d['tambah_harga_sak'], d['tambah_isi_sak']
    )
    await query.edit_message_text(
        f"✅ *Bahan berhasil ditambahkan!*\n\n"
        f"🆔 ID: {new_id}\n"
        f"📦 *{d['tambah_nama']}*\n"
        f"💰 Harga/{d['tambah_satuan']}: *{fmt_rp(harga_satuan)}*\n\n"
        "_Tersimpan di Google Sheets_ ✓",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(back_button())
    )
    return MENU

# ─── CEK HARGA ────────────────────────────────────────────────────────────────
async def menu_cek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔍 *Cek Harga Bahan*\n\nKetik nama bahan yang ingin dicek:",
        parse_mode="Markdown"
    )
    return CEK_NAMA

async def cek_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.strip()
    hasil = cari_bahan(keyword)

    if not hasil:
        await update.message.reply_text(
            f"❌ Bahan *{keyword}* tidak ditemukan.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Tambah bahan ini", callback_data=f"beli_tambah_baru:{keyword}")],
                [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")],
            ])
        )
        return MENU

    text = f"🔍 *Hasil: \"{keyword}\"*\n\n"
    for b in hasil:
        text += (
            f"📦 *{b['Nama Bahan']}*\n"
            f"   Satuan: {b['Satuan Terkecil']}\n"
            f"   Harga/sak ({b['Isi per Sak']} {b['Satuan Terkecil']}): {fmt_rp(b['Harga/Sak (Rp)'])}\n"
            f"   Harga/{b['Satuan Terkecil']}: *{fmt_rp(b['Harga per Satuan Terkecil'])}*\n\n"
        )

    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(back_button())
    )
    return MENU

# ─── RIWAYAT ──────────────────────────────────────────────────────────────────
async def menu_riwayat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📋 *Riwayat Pembelian*\nTampilkan berapa transaksi terakhir?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("10 terakhir", callback_data="riwayat:10"),
             InlineKeyboardButton("20 terakhir", callback_data="riwayat:20")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")],
        ])
    )
    return MENU

async def riwayat_tampil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    limit = int(query.data.split(":")[1])
    records = get_riwayat(limit)

    if not records:
        await query.edit_message_text(
            "📭 Belum ada riwayat pembelian.",
            reply_markup=InlineKeyboardMarkup(back_button())
        )
        return MENU

    text = f"📋 *{limit} Transaksi Terakhir*\n\n"
    for r in reversed(records):
        text += (
            f"🕐 {r.get('Tanggal','')}\n"
            f"   {r.get('Nama Bahan','')} — {r.get('Jumlah','')} {r.get('Satuan','')}\n"
            f"   💰 {fmt_rp(r.get('Total (Rp)',0))}\n\n"
        )

    await query.edit_message_text(
        text[:4000], parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(back_button())
    )
    return MENU

# ─── REKAP ────────────────────────────────────────────────────────────────────
async def menu_rekap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    now = datetime.now()
    bulan_ini = now.strftime("%Y-%m")
    if now.month == 1:
        bulan_lalu = f"{now.year - 1}-12"
    else:
        bulan_lalu = f"{now.year}-{now.month - 1:02d}"

    await query.edit_message_text(
        "📊 *Rekap Pengeluaran*\nPilih periode:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📅 Bulan ini ({bulan_ini})", callback_data=f"rekap:{bulan_ini}")],
            [InlineKeyboardButton(f"📅 Bulan lalu ({bulan_lalu})", callback_data=f"rekap:{bulan_lalu}")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")],
        ])
    )
    return MENU

async def rekap_tampil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bulan = query.data.split(":")[1]
    records, total = get_rekap_bulan(bulan)

    if not records:
        await query.edit_message_text(
            f"📭 Tidak ada transaksi di *{bulan}*.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(back_button())
        )
        return MENU

    per_bahan = {}
    for r in records:
        nama = r.get('Nama Bahan', 'Unknown')
        per_bahan[nama] = per_bahan.get(nama, 0) + r.get('Total (Rp)', 0)

    text = (
        f"📊 *Rekap {bulan}*\n\n"
        f"Transaksi: {len(records)}x\n"
        f"*Total: {fmt_rp(total)}*\n\n"
        f"Per bahan:\n"
    )
    for nama, tot in sorted(per_bahan.items(), key=lambda x: x[1], reverse=True):
        text += f"  • {nama}: {fmt_rp(tot)}\n"

    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(back_button())
    )
    return MENU

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU: [
                CallbackQueryHandler(show_main_menu, pattern="^main_menu$"),
                CallbackQueryHandler(menu_beli, pattern="^menu_beli$"),
                CallbackQueryHandler(menu_tambah, pattern="^menu_tambah$"),
                CallbackQueryHandler(menu_cek, pattern="^menu_cek$"),
                CallbackQueryHandler(menu_riwayat, pattern="^menu_riwayat$"),
                CallbackQueryHandler(menu_rekap, pattern="^menu_rekap$"),
                CallbackQueryHandler(riwayat_tampil, pattern="^riwayat:"),
                CallbackQueryHandler(rekap_tampil, pattern="^rekap:"),
                CallbackQueryHandler(tambah_dari_beli, pattern="^beli_tambah_baru:"),
            ],
            BELI_CARI: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, beli_cari),
                CallbackQueryHandler(menu_beli, pattern="^menu_beli$"),
                CallbackQueryHandler(show_main_menu, pattern="^main_menu$"),
            ],
            BELI_PILIH: [
                CallbackQueryHandler(beli_pilih, pattern="^beli_pilih:"),
                CallbackQueryHandler(menu_beli, pattern="^menu_beli$"),
            ],
            BELI_JUMLAH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, beli_jumlah),
            ],
            BELI_SATUAN: [
                CallbackQueryHandler(beli_satuan, pattern="^beli_satuan:"),
            ],
            BELI_HARGA_MANUAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, beli_harga_manual),
            ],
            BELI_KONFIRMASI: [
                CallbackQueryHandler(beli_simpan, pattern="^beli_simpan$"),
                CallbackQueryHandler(show_main_menu, pattern="^main_menu$"),
            ],
            TAMBAH_NAMA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, tambah_nama),
            ],
            TAMBAH_SATUAN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, tambah_satuan),
                CallbackQueryHandler(tambah_dari_beli, pattern="^beli_tambah_baru:"),
            ],
            TAMBAH_HARGA_SAK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, tambah_harga_sak),
            ],
            TAMBAH_ISI_SAK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, tambah_isi_sak),
            ],
            TAMBAH_KONFIRMASI: [
                CallbackQueryHandler(tambah_simpan, pattern="^tambah_simpan$"),
                CallbackQueryHandler(show_main_menu, pattern="^main_menu$"),
            ],
            CEK_NAMA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cek_nama),
                CallbackQueryHandler(tambah_dari_beli, pattern="^beli_tambah_baru:"),
                CallbackQueryHandler(show_main_menu, pattern="^main_menu$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(show_main_menu, pattern="^main_menu$"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    logger.info("Bot started polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
