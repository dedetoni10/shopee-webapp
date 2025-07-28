from flask import render_template, redirect, url_for, flash, request, session, jsonify, get_flashed_messages
from flask_login import login_required, current_user
from extensions import db, get_app_trial_status
import datetime
from flask_wtf.csrf import generate_csrf
import pandas as pd
import numpy as np
import io

from . import bp
from models import App, UserApp

# --- GLOBAL CONSTANTS ---
SHOPEE_ROAS_CAP = 50.0  # ROAS maksimal yang bisa diset di Shopee
SHOPEE_MIN_DAILY_BUDGET = 5000  # Minimal modal harian di Shopee

# --- DEFAULT ASSUMPTIONS FOR PROFIT CALCULATION (IF NOT AVAILABLE FROM CSV OR USER INPUT) ---
# Ini adalah asumsi. Digunakan jika user tidak memberikan input di form hitung ulang.
DEFAULT_MODAL_PRODUCT_RATIO = 0.50   # Modal produk 50% dari harga jual
DEFAULT_SHOPEE_FEE_PERCENT = 0.05    # Fee Shopee 5% dari harga jual
DEFAULT_ADDITIONAL_COST_PER_UNIT = 1000 # Biaya tambahan per unit Rp1000
DEFAULT_TARGET_PROFIT_PERCENT = 0.10 # Target profit 10% dari omzet


# --- GLOBAL HELPER FUNCTIONS ---
# Menambahkan harga_jual_per_unit_input sebagai parameter opsional di fungsi get_recommendation
def get_recommendation(row_data, modal_produk_input=None, fee_shopee_input=None, biaya_tambahan_input=None, target_profit_pct_input=None, harga_jual_per_unit_input=None):
    """
    Menerapkan logika rekomendasi pada setiap baris data produk.
    Mendukung input override dari form Hitung Ulang untuk perhitungan profitabilitas akurat.
    Menambahkan harga_jual_per_unit_input untuk kasus Analisa Manual/Hitung Ulang yang memberikan harga jual langsung.
    """
    # Mengambil data dari baris DataFrame (sudah di-camelCase-kan)
    # Penting: Pastikan semua nilai yang diambil diubah menjadi float atau 0 jika None/NaN
    produk_id = row_data.get('produkId')
    nama_produk = row_data.get('namaProduk') # Nama produk diambil dari row_data
    
    # Pastikan roas_aktual, biaya, omzetPenjualan, produkTerjual selalu ada dan numerik
    roas_aktual = float(row_data.get('ROAS') or 0)
    biaya_iklan_aktual = float(row_data.get('biaya') or 0)
    omzet_penjualan_aktual = float(row_data.get('omzetPenjualan') or 0)
    produk_terjual_aktual = float(row_data.get('produkTerjual') or 0)
    
    # CTR tidak lagi digunakan untuk logika utama, hanya untuk penjelasan detail jika ada
    ctr = float(row_data.get('persentaseKlik') or 0) 

    # Ambil nilai override dari input user (form Hitung Ulang atau Analisa Manual)
    # Untuk Analisa Manual, kita akan langsung menggunakan modal_produk_input, fee_shopee_input, dll.
    # Untuk CSV, nilai-nilai ini akan None, sehingga akan menggunakan DEFAULT assumptions.
    final_modal_produk = float(modal_produk_input) if modal_produk_input is not None else (DEFAULT_MODAL_PRODUCT_RATIO * (omzet_penjualan_aktual / produk_terjual_aktual if produk_terjual_aktual > 0 else 0))
    final_fee_shopee_pct = float(fee_shopee_input) if fee_shopee_input is not None else DEFAULT_SHOPEE_FEE_PERCENT
    final_biaya_tambahan = float(biaya_tambahan_input) if biaya_tambahan_input is not None else DEFAULT_ADDITIONAL_COST_PER_UNIT
    final_target_profit_pct = float(target_profit_pct_input) if target_profit_pct_input is not None else DEFAULT_TARGET_PROFIT_PERCENT

    # Inisialisasi default hasil rekomendasi
    tag = 'default'
    analisa_text = "Belum Ada Data/Tidak Ada Aktivitas Iklan"
    rekomendasi_aksi_text = "BELUM ADA REKOMENDASI"
    roas_target_optimal_val = "N/A"
    rekomendasi_modal_harian_text = "N/A"
    detailed_explanation = "Tidak ada data iklan yang cukup untuk menganalisis produk ini. Pastikan data Omzet Penjualan, Produk Terjual, dan Biaya Iklan terisi. Untuk analisis lebih akurat, gunakan fitur 'Hitung Ulang'."

    # --- Tentukan nilai-nilai untuk perhitungan profit (menggunakan input override atau data aktual) ---
    # Harga Jual Per Unit: Prioritaskan harga_jual_per_unit_input jika diberikan
    if harga_jual_per_unit_input is not None and harga_jual_per_unit_input > 0:
        current_harga_jual = float(harga_jual_per_unit_input)
    else:
        current_harga_jual = omzet_penjualan_aktual / produk_terjual_aktual if produk_terjual_aktual > 0 else 0
    
    # Jika harga jual per unit masih 0 atau tidak valid setelah perhitungan awal, tidak bisa lanjut
    if current_harga_jual <= 0 and (omzet_penjualan_aktual > 0 or produk_terjual_aktual > 0 or (modal_produk_input is not None or fee_shopee_input is not None or biaya_tambahan_input is not None or target_profit_pct_input is not None)) :
        # Ini kasus di mana omzet ada tapi produk terjual 0, atau harga jual = 0. Tidak bisa dihitung per unit.
        # Atau jika harga_jual_input dari form recalculate adalah 0.
        detailed_explanation = "Harga jual per unit tidak dapat dihitung dengan data Omzet dan Produk Terjual yang diberikan, atau harga jual yang dimasukkan tidak valid. Pastikan Harga Jual > 0 jika di Analisa Manual/Hitung Ulang, atau Omzet Penjualan dan Produk Terjual > 0 jika dari laporan CSV."
        return analisa_text, rekomendasi_aksi_text, roas_target_optimal_val, tag, detailed_explanation, rekomendasi_modal_harian_text
    elif current_harga_jual <= 0: # Ini kondisi kalau omzet juga 0, berarti belum ada penjualan sama sekali
        # Biarkan default explanation
        return analisa_text, rekomendasi_aksi_text, roas_target_optimal_val, tag, detailed_explanation, rekomendasi_modal_harian_text
            
    # Modal Produk (gunakan input override jika ada, jika tidak, pakai asumsi atau hitung dari harga jual aktual)
    # Ini sudah dihandle di final_modal_produk, tidak perlu diubah lagi
    current_modal_produk = final_modal_produk
    
    # Fee Shopee
    current_fee_shopee_pct = final_fee_shopee_pct

    # Biaya Tambahan
    current_biaya_tambahan = final_biaya_tambahan

    # Target Profit Percentage
    current_target_profit_pct = final_target_profit_pct

    # --- Hitung Biaya Pokok Total Per Unit ---
    biaya_pokok_total_per_unit = current_modal_produk + (current_harga_jual * current_fee_shopee_pct) + current_biaya_tambahan

    # --- Hitung ROAS Break-Even Produk ---
    profit_kotor_per_unit = current_harga_jual - biaya_pokok_total_per_unit

    roas_break_even_produk = 0
    if profit_kotor_per_unit > 0:
        roas_break_even_produk = current_harga_jual / profit_kotor_per_unit
    else:
        roas_break_even_produk = np.inf # Tidak mungkin untung jika profit kotor <= 0
    
    display_roas_break_even_produk = min(roas_break_even_produk, SHOPEE_ROAS_CAP) if np.isfinite(roas_break_even_produk) else "N/A"
    if display_roas_break_even_produk == "N/A" and profit_kotor_per_unit <= 0 :
        display_roas_break_even_produk = "Tak Terhingga" # Lebih jelas kalau tidak bisa untung

    # --- Hitung Biaya Iklan Maksimum per Unit untuk Target Profit ---
    laba_diharapkan_per_unit_target = current_harga_jual * current_target_profit_pct
    max_iklan_per_unit_for_target_profit = current_harga_jual - (biaya_pokok_total_per_unit + laba_diharapkan_per_unit_target)

    roas_target_profit_needed = 0
    if max_iklan_per_unit_for_target_profit > 0:
        roas_target_profit_needed = current_harga_jual / max_iklan_per_unit_for_target_profit
    else:
        roas_target_profit_needed = np.inf # Tidak mungkin capai profit target jika biaya iklan maksimal <= 0

    display_roas_target_profit_needed = min(roas_target_profit_needed, SHOPEE_ROAS_CAP) if np.isfinite(roas_target_profit_needed) else "N/A"


    # --- Format data untuk display di penjelasan detail dan tabel ---
    formatted_biaya_iklan_aktual = f"Rp{biaya_iklan_aktual:,.0f}" if np.isfinite(biaya_iklan_aktual) and biaya_iklan_aktual > 0 else "Rp0"
    formatted_omzet_penjualan_aktual = f"Rp{omzet_penjualan_aktual:,.0f}" if np.isfinite(omzet_penjualan_aktual) and omzet_penjualan_aktual > 0 else "Rp0"
    formatted_produk_terjual_plural = f"{int(produk_terjual_aktual):,} unit" if np.isfinite(produk_terjual_aktual) else "N/A unit"
    formatted_roas_aktual = f"{roas_aktual:,.2f}" if np.isfinite(roas_aktual) else "N/A"
    formatted_ctr = f"{ctr*100:,.2f}%" if np.isfinite(ctr) else "N/A"

    # --- Logika Rekomendasi Utama (lebih cerdas berdasarkan BEP dan Target Profit) ---
    if np.isfinite(roas_aktual) and np.isfinite(biaya_iklan_aktual) and biaya_iklan_aktual > 0:
        # Menghitung profit bersih aktual
        profit_bersih_aktual = omzet_penjualan_aktual - (biaya_iklan_aktual + (biaya_pokok_total_per_unit * produk_terjual_aktual))
        target_profit_omzet_aktual = omzet_penjualan_aktual * current_target_profit_pct

        if roas_aktual >= roas_target_profit_needed: # Sangat efisien, sudah melampaui target profit
            tag = 'sangat_baik'
            analisa_text = "Luar Biasa (Sangat Efisien dan Sangat Profitable!)"
            rekomendasi_aksi_text = "MAKSIMALKAN ANGGARAN"
            roas_target_optimal_val = f"{SHOPEE_ROAS_CAP:.1f}" # Dorong ke batas Shopee untuk volume
            
            # Modal harian direkomendasikan dinaikkan secara agresif, tapi tetap di atas minimal Shopee
            modal_harian_rekomendasi_val = max(SHOPEE_MIN_DAILY_BUDGET, biaya_iklan_aktual * 3)
            rekomendasi_modal_harian_text = f"Rp{modal_harian_rekomendasi_val:,.0f}"

            detailed_explanation = (
                f"Produk ini menunjukkan efisiensi iklan yang **sangat luar biasa** dengan ROAS aktual sebesar {formatted_roas_aktual}. "
                f"ROAS Titik Impas produk ini adalah {display_roas_break_even_produk}, dan Anda bahkan melampaui target profit {current_target_profit_pct*100:.0f}%! "
                f"Dengan biaya iklan {formatted_biaya_iklan_aktual} menghasilkan omzet {formatted_omzet_penjualan_aktual} dari {formatted_produk_terjual_plural} terjual, profit Anda sangat tinggi. "
                f"**Sangat direkomendasikan untuk menaikkan anggaran iklan Anda secara agresif.** Anda dapat menetapkan Target ROAS di Shopee ke **{SHOPEE_ROAS_CAP:.1f}** (batas maksimal yang bisa diset) untuk memaksimalkan volume penjualan yang lebih besar."
            )
        elif roas_aktual > roas_break_even_produk: # Cukup efisien, di atas BEP tapi belum tentu capai target profit
            if profit_bersih_aktual >= target_profit_omzet_aktual:
                tag = 'sangat_baik'
                analisa_text = "Sangat Baik (Efisien dan Sesuai Target Profit)"
                rekomendasi_aksi_text = "NAIKKAN ANGGARAN BERTAHAP"
                # Target ROAS optimal bisa di atas ROAS aktual sedikit
                target_calc = max(roas_aktual * 1.05, roas_target_profit_needed) # Naikkan 5% dari aktual, atau capai target profit
                roas_target_optimal_val = f"{min(SHOPEE_ROAS_CAP, target_calc):.1f}"
                
                modal_harian_rekomendasi_val = max(SHOPEE_MIN_DAILY_BUDGET, biaya_iklan_aktual * 1.5)
                rekomendasi_modal_harian_text = f"Rp{modal_harian_rekomendasi_val:,.0f}"

                detailed_explanation = (
                    f"Performa iklan produk ini **sangat baik** dengan ROAS aktual sebesar {formatted_roas_aktual}. "
                    f"Anda sudah mencapai atau melampaui target profit {current_target_profit_pct*100:.0f}% Anda! "
                    f"Anda mendapatkan omzet {formatted_omzet_penjualan_aktual} dengan biaya iklan {formatted_biaya_iklan_aktual} dari {formatted_produk_terjual_plural} terjual. "
                    f"Ini menunjukkan efisiensi yang tinggi dan potensi pertumbuhan yang baik. "
                    f"**Disarankan untuk menaikkan anggaran iklan Anda secara bertahap dan memantau hasilnya.** Anda dapat menargetkan ROAS sekitar **{roas_target_optimal_val}** di Shopee untuk menjaga profit dan meningkatkan penjualan."
                )
            else:
                tag = 'cukup_baik'
                analisa_text = "Cukup Baik (Untung, Namun Perlu Optimasi untuk Target Profit)"
                rekomendasi_aksi_text = "PERTAHANKAN & OPTIMASI KONTEN/TARGETING/HARGA"
                # Target ROAS optimal, sedikit di atas BEP, atau target profit
                target_calc = max(roas_aktual * 1.05, roas_break_even_produk * 1.1)
                roas_target_optimal_val = f"{min(SHOPEE_ROAS_CAP, target_calc):.1f}"
                
                modal_harian_rekomendasi_val = max(SHOPEE_MIN_DAILY_BUDGET, biaya_iklan_aktual * 1.0) # Pertahankan anggaran
                rekomendasi_modal_harian_text = f"Rp{modal_harian_rekomendasi_val:,.0f}"

                detailed_explanation = (
                    f"Produk ini memiliki ROAS aktual {formatted_roas_aktual}, yang tergolong **cukup efisien** (di atas ROAS Titik Impas {display_roas_break_even_produk}), namun belum mencapai target profit {current_target_profit_pct*100:.0f}% Anda. "
                    f"Meskipun sudah menghasilkan omzet {formatted_omzet_penjualan_aktual} dari {formatted_produk_terjual_plural} terjual dengan biaya iklan {formatted_biaya_iklan_aktual}, ada ruang untuk peningkatan efisiensi agar sesuai target profit. "
                    f"**Pertahankan iklan ini, namun fokus pada optimasi lebih lanjut.** "
                    f"Pertimbangkan untuk memperbarui judul/gambar produk, menyesuaikan targeting audiens, menguji kata kunci baru, atau bahkan meninjau harga jual dan biaya pokok Anda untuk mencapai ROAS yang lebih tinggi (targetkan **{roas_target_optimal_val}**) dan profit yang sesuai target."
                )
        elif 0 < roas_aktual <= roas_break_even_produk:
            tag = 'boncos'
            analisa_text = "Kurang Efisien (Rugi!)"
            rekomendasi_aksi_text = "TURUNKAN ANGGARAN / FOKUS OPTIMASI EKSTREM / JEDA IKLAN"
            # Targetkan ROAS sedikit di atas BEP agar bisa balik modal
            roas_target_optimal_val = f"{min(SHOPEE_ROAS_CAP, roas_break_even_produk * 1.1):.1f}"
            
            # Modal harian direkomendasikan diturunkan drastis, atau bahkan dihentikan
            modal_harian_rekomendasi_val = max(SHOPEE_MIN_DAILY_BUDGET, biaya_iklan_aktual * 0.3)
            rekomendasi_modal_harian_text = f"Rp{modal_harian_rekomendasi_val:,.0f}"

            detailed_explanation = (
                f"ROAS aktual produk ini adalah {formatted_roas_aktual}, yang tergolong **sangat kurang efisien** dan kemungkinan besar merugi (di bawah atau sangat dekat dengan ROAS Titik Impas {display_roas_break_even_produk}). "
                f"Biaya iklan {formatted_biaya_iklan_aktual} jauh terlalu tinggi dibandingkan hasil penjualan {formatted_omzet_penjualan_aktual} dari {formatted_produk_terjual_plural} terjual, mengakibatkan kerugian. "
                f"**Disarankan untuk segera menurunkan anggaran iklan Anda secara signifikan atau bahkan jeda iklan ini.** "
                f"Fokus pada perbaikan mendalam pada iklan (target, bid, konten) atau halaman produk. Jika tidak ada perbaikan, pertimbangkan untuk menghentikan iklan ini. Targetkan ROAS minimal **{roas_target_optimal_val}** untuk mulai balik modal."
            )
        elif biaya_iklan_aktual > 0 and (not np.isfinite(roas_aktual) or roas_aktual == 0):
            tag = 'boncos'
            if np.isfinite(ctr) and ctr < 0.01:
                analisa_text = "Iklan Tidak Menarik (CTR Rendah)"
                rekomendasi_aksi_text = "JEDA & GANTI KONTEN/VISUAL/JUDUL"
                roas_target_optimal_val = "N/A"
                rekomendasi_modal_harian_text = "Rp0"

                detailed_explanation = (
                    f"Iklan ini telah menghabiskan biaya {formatted_biaya_iklan_aktual} tanpa menghasilkan penjualan (ROAS {formatted_roas_aktual} / N/A). "
                    f"Persentase klik (CTR) yang sangat rendah ({formatted_ctr}) menunjukkan bahwa iklan Anda tidak menarik perhatian pembeli. "
                    f"**Segera jeda iklan ini.** Fokus pada perbaikan elemen kreatif seperti judul produk, gambar utama, dan video produk. "
                    f"Pastikan iklan Anda relevan dan menonjol di halaman pencarian atau rekomendasi agar mendapatkan lebih banyak klik."
                )
            else:
                analisa_text = "Produk Tidak Meyakinkan (CTR Baik, tapi Tanpa Konversi)"
                rekomendasi_aksi_text = "JEDA & OPTIMASI HARGA/PROMO/DESKRIPSI"
                roas_target_optimal_val = "N/A"
                rekomendasi_modal_harian_text = "Rp0"

                detailed_explanation = (
                    f"Meskipun iklan ini mendapatkan klik (CTR {formatted_ctr}) dengan biaya {formatted_biaya_iklan_aktual}, tidak ada penjualan yang terjadi (ROAS {formatted_roas_aktual} / N/A). "
                    f"Ini menunjukkan bahwa pembeli mungkin tertarik pada iklan Anda, tetapi tidak yakin untuk membeli setelah melihat halaman produk. "
                    f"**Jeda iklan ini dan fokus pada optimasi halaman produk Anda.** Perbaiki harga, tambahkan promo menarik, "
                    f"perjelas deskripsi produk, perbanyak ulasan positif, atau tingkatkan kualitas gambar/video produk untuk meningkatkan konversi."
                )
    else:
        analisa_text = "Belum Ada Data/Tidak Ada Aktivitas Iklan"
        rekomendasi_aksi_text = "MULAI IKLAN / PERIKSA DATA"
        roas_target_optimal_val = "N/A"
        tag = 'netral'
        rekomendasi_modal_harian_text = "N/A"
        detailed_explanation = "Tidak ada data iklan yang cukup untuk menganalisis produk ini. Pastikan produk ini memiliki aktivitas iklan yang memadai dan statusnya 'Berjalan', serta Omzet Penjualan, Produk Terjual, dan Biaya Iklan terisi. Jika ini iklan baru, gunakan mode 'Iklan Baru'."


    if roas_target_optimal_val is None or roas_target_optimal_val == "": roas_target_optimal_val = "N/A"
    if rekomendasi_modal_harian_text is None or rekomendasi_modal_harian_text == "": rekomendasi_modal_harian_text = "N/A"

    return analisa_text, rekomendasi_aksi_text, roas_target_optimal_val, tag, detailed_explanation, rekomendasi_modal_harian_text


def get_row_color_tag(profit_val, target_profit_threshold, is_profit_positive):
    if profit_val >= target_profit_threshold:
        return 'sangat_baik'
    elif is_profit_positive:
        return 'cukup_baik'
    else:
        return 'boncos'

# --- ROUTES ---

@bp.route('/')
@login_required
def index():
    app_info = App.query.filter_by(url='roas_calculator').first()
    if not app_info:
        flash('Aplikasi tidak ditemukan.', 'danger')
        return redirect(url_for('dashboard.index'))

    user_app_entry = UserApp.query.filter_by(user_id=current_user.id, app_id=app_info.id).first()
    if not user_app_entry:
        flash('Kamu perlu menginstal aplikasi ini dari App Store untuk membukanya.', 'warning')
        return redirect(url_for('app_store.index'))

    app_status = get_app_trial_status(current_user.id, app_info.url)

    current_mode = session.get('calculator_roas_mode', 'baru')
    raw_result_data = session.get('calculator_roas_result', None)
    
    result_data = {
        'label_hasil': '',
        'label_keterangan': '',
        'table_data': [],
        'table_headers': [],
        'products_data': [],
        'mode': current_mode
    }

    if raw_result_data:
        result_data['label_hasil'] = raw_result_data.get('label_hasil', '')
        # Jika label_keterangan adalah list, gabungkan untuk display awal
        if isinstance(raw_result_data.get('label_keterangan'), list):
            result_data['label_keterangan'] = "\n".join(raw_result_data['label_keterangan'])
        else:
            result_data['label_keterangan'] = raw_result_data.get('label_keterangan', '')
        result_data['table_data'] = raw_result_data.get('table_data', [])
        result_data['table_headers'] = raw_result_data.get('table_headers', [])
        result_data['products_data'] = raw_result_data.get('products_data', [])
        result_data['mode'] = raw_result_data.get('mode', current_mode)

    return render_template(
        'roas_calculator.html',
        app_name=app_info.name,
        time_remaining_seconds=int(app_status['time_remaining_seconds']),
        trial_expired=app_status['trial_expired'],
        is_premium_active=app_status['is_premium_active'],
        notification_message_prefix=app_status['notification_message_prefix'],
        notification_type=app_status['notification_type'],
        whatsapp_number=app_status['whatsapp_number'],
        mode=current_mode,
        result=result_data,
        csrf_token=generate_csrf()
    )

@bp.route('/detail/<app_url>')
@login_required
def detail(app_url):
    app_info = App.query.filter_by(url=app_url).first()
    if not app_info:
        flash('Aplikasi tidak ditemukan.', 'danger')
        return redirect(url_for('app_store.index'))

    user_app_entry = UserApp.query.filter_by(user_id=current_user.id, app_id=app_info.id).first()
    is_installed = user_app_entry is not None

    app_status = get_app_trial_status(current_user.id, app_info.url)

    return render_template(
        'app_detail.html',
        app=app_info,
        is_installed=is_installed,
        time_remaining_seconds=int(app_status['time_remaining_seconds']),
        trial_expired=app_status['trial_expired'],
        is_premium_active=app_status['is_premium_active'],
        notification_message_prefix=app_status['notification_message_prefix'],
        notification_type=app_status['notification_type'],
        whatsapp_number=app_status['whatsapp_number'],
        csrf_token=generate_csrf()
    )


@bp.route('/analyze', methods=['POST'])
@login_required
def analyze():
    print("\n--- Received analyze request ---")
    mode = request.form.get('mode')
    print(f"Mode received: {mode}")

    result_data = {'label_hasil': '', 'label_keterangan': [], 'table_data': [], 'table_headers': [], 'products_data': []}
    flash_messages = []

    app_info = App.query.filter_by(url='roas_calculator').first()
    if not app_info:
        flash_messages.append({'category': 'danger', 'message': 'Aplikasi tidak ditemukan di backend. Hubungi administrator.'})
        return jsonify({
            'mode': mode,
            'result': result_data,
            'flash_messages': flash_messages
        })

    app_status = get_app_trial_status(current_user.id, app_info.url)
    if app_status['trial_expired'] and not app_status['is_premium_active']:
        flash_messages.append({'category': 'danger', 'message': app_status['notification_message_prefix'] + " Harap perbarui langganan Anda."})
        return jsonify({
            'mode': mode,
            'result': result_data,
            'flash_messages': flash_messages
        })

    if mode == 'baru':
        try:
            modal = float(request.form.get('modal') or 0)
            harga_jual = float(request.form.get('harga_jual') or 0)
            fee = float(request.form.get('fee') or 0) / 100
            tambahan = float(request.form.get('tambahan') or 0)
            target_profit_pct = float(request.form.get('profit') or 0) / 100
            
            estimated_produk_terjual_str = request.form.get('estimated_produk_terjual')
            sim_base_units = float(estimated_produk_terjual_str) if estimated_produk_terjual_str and float(estimated_produk_terjual_str) > 0 else 1

            if not (modal >= 0 and harga_jual > 0 and fee >= 0 and tambahan >= 0 and target_profit_pct >= 0):
                raise ValueError("Pastikan semua input (Modal, Harga Jual, Fee, Biaya Tambahan, Target Profit) adalah angka positif yang valid.")
            
            biaya_fee = harga_jual * fee
            total_cost_per_unit_excluding_ads = modal + biaya_fee + tambahan

            if harga_jual <= total_cost_per_unit_excluding_ads and target_profit_pct > 0:
                flash_messages.append({
                    'category': 'warning',
                    'message': f"Harga jual (Rp{harga_jual:,.0f}) terlalu rendah atau biaya (Rp{total_cost_per_unit_excluding_ads:,.0f}) terlalu tinggi untuk mencapai target profit {target_profit_pct*100:.0f}%. Produk ini akan rugi bahkan tanpa biaya iklan."
                })
                # Set values that indicate unprofitability
                max_iklan_per_unit_for_target_profit = -1
                roas_target_profit_needed = 999999.0
            else:
                laba_diharapkan_per_unit = harga_jual * target_profit_pct
                
                max_iklan_per_unit_for_target_profit = harga_jual - (total_cost_per_unit_excluding_ads + laba_diharapkan_per_unit)

                roas_target_profit_needed = 0
                if max_iklan_per_unit_for_target_profit > 0:
                    roas_target_profit_needed = harga_jual / max_iklan_per_unit_for_target_profit
                else:
                    roas_target_profit_needed = 999999.0 # Indicates it's very hard to reach target profit

            biaya_iklan_bep_per_unit = harga_jual - total_cost_per_unit_excluding_ads
            roas_break_even = 0
            if biaya_iklan_bep_per_unit > 0:
                roas_break_even = harga_jual / biaya_iklan_bep_per_unit
            else:
                roas_break_even = -1 # Indicates already profitable without ads

            display_roas_target_profit_needed = min(roas_target_profit_needed, SHOPEE_ROAS_CAP)
            display_roas_break_even = min(roas_break_even, SHOPEE_ROAS_CAP) if roas_break_even > 0 else 0


            roas_rekomendasi_final = roas_target_profit_needed
            if roas_rekomendasi_final > SHOPEE_ROAS_CAP:
                result_data['label_hasil'] = f"✨ Rekomendasi ROAS Anda: Target ROAS optimal: **{SHOPEE_ROAS_CAP:,.2f}** (maks Shopee). Profit Anda sangat tinggi! Fokus pada peningkatan volume penjualan."
            elif roas_rekomendasi_final <= 0 or (harga_jual <= total_cost_per_unit_excluding_ads and target_profit_pct > 0):
                result_data['label_hasil'] = "✨ Rekomendasi ROAS Anda: Produk ini sulit/tidak mungkin untung dengan harga & biaya yang ada. Pertimbangkan menaikkan harga jual, mengurangi modal/biaya, atau menurunkan target profit."
            else:
                result_data['label_hasil'] = f"✨ Rekomendasi ROAS Anda: Target ROAS optimal untuk {target_profit_pct*100:.0f}% profit: **{display_roas_target_profit_needed:,.2f}**"
            
            
            # Keterangan detail untuk mode Iklan Baru
            result_data['label_keterangan'].append(f"Titik Impas (Break-Even Point) ROAS: **{display_roas_break_even:,.2f}** (ROAS minimal yang harus dicapai agar tidak rugi. Jika kurang dari ini, Anda BONCOS!)")
            
            if max_iklan_per_unit_for_target_profit > 0:
                result_data['label_keterangan'].append(f"Biaya Iklan Maksimum per unit terjual (untuk capai {target_profit_pct*100:.0f}% profit): Rp{max_iklan_per_unit_for_target_profit:,.0f}")
            else:
                result_data['label_keterangan'].append(f"Biaya Iklan Maksimum per unit terjual: Tidak memungkinkan profit dengan target ini. Nilai negatif atau nol menunjukkan biaya produk sudah melebihi harga jual.")

            estimated_profit_total_at_target_roas = (harga_jual * sim_base_units) - \
                                                    ((harga_jual * sim_base_units) / roas_rekomendasi_final if roas_rekomendasi_final > 0 else 0) - \
                                                    (total_cost_per_unit_excluding_ads * sim_base_units)
            if sim_base_units > 0:
                result_data['label_keterangan'].append(f"Estimasi Profit Total (jika terjual {int(sim_base_units)} unit dan capai target ROAS): Rp{estimated_profit_total_at_target_roas:,.0f}")
            else:
                   result_data['label_keterangan'].append(f"Estimasi Profit Total: Untuk estimasi profit, masukkan jumlah produk terjual yang diinginkan.")


            table_headers = ("ROAS", "Biaya Iklan", "Omzet Penjualan", "Profit Total", "Trafik", "Keterangan")
            table_data = []

            # Generate simulation table data based on calculated ROAS
            sim_roas_values = []
            
            # Add target profit ROAS
            if np.isfinite(roas_target_profit_needed) and roas_target_profit_needed > 0:
                sim_roas_values.append(min(roas_target_profit_needed, SHOPEE_ROAS_CAP))

            # Add break-even ROAS
            if np.isfinite(roas_break_even) and roas_break_even > 0 and roas_break_even != roas_target_profit_needed:
                sim_roas_values.append(min(roas_break_even, SHOPEE_ROAS_CAP))
            elif roas_break_even <= 0 and 0.0 not in sim_roas_values: # If product is always profitable, add 0 ROAS as a point
                sim_roas_values.append(0.01) # Use a very small positive ROAS to represent almost no ad cost

            # Add values around the target profit ROAS and break-even ROAS
            base_roas_for_sim = roas_target_profit_needed if np.isfinite(roas_target_profit_needed) and roas_target_profit_needed > 0 else roas_break_even if np.isfinite(roas_break_even) and roas_break_even > 0 else 10.0

            # Ensure there's a range of values if possible
            range_values = [base_roas_for_sim, base_roas_for_sim + 5, base_roas_for_sim + 10,
                            max(1.0, base_roas_for_sim - 5), max(1.0, base_roas_for_sim - 10)]
            
            # Add SHOPEE_ROAS_CAP if not already close
            if SHOPEE_ROAS_CAP not in sim_roas_values:
                sim_roas_values.append(SHOPEE_ROAS_CAP)

            for val in range_values:
                if val > 0 and val <= SHOPEE_ROAS_CAP and val not in sim_roas_values:
                    sim_roas_values.append(val)
            
            sim_roas_values = sorted(list(set([round(x, 2) for x in sim_roas_values if x > 0])), reverse=True) # Unique, sorted, positive

            # Limit to a reasonable number of rows for display
            if len(sim_roas_values) > 5:
                sim_roas_values = sim_roas_values[:5] # Take top 5 highest ROAS values

            for r_val in sim_roas_values:
                table_data.append(calculate_row_for_simulation(
                    r_val, harga_jual, sim_base_units, total_cost_per_unit_excluding_ads, target_profit_pct, roas_break_even
                ))
            
            table_data.sort(key=lambda x: float(x[0].replace(',', '')), reverse=True) # Sort by ROAS
            
            result_data['table_headers'] = table_headers
            result_data['table_data'] = table_data
            flash_messages.append({'category': 'success', 'message': 'Analisis Iklan Baru berhasil!'})

        except ValueError as e:
            flash_messages.append({'category': 'danger', 'message': f"Isi semua kolom dengan angka yang valid dan periksa nilai input. Detail: {e}"})
            print(f"DEBUG: ValueError in mode 'baru': {e}")
        except Exception as e:
            flash_messages.append({'category': 'danger', 'message': f"Terjadi kesalahan saat menghitung mode Iklan Baru: {e}"})
            print(f"DEBUG: General Exception in mode 'baru': {e}")

    elif mode == 'jalan':
        try:
            # Mengambil input yang sudah disederhanakan
            biaya_iklan_aktual = float(request.form.get('biaya_iklan_aktual') or 0)
            omzet_penjualan_aktual = float(request.form.get('omzet_penjualan_aktual') or 0)
            produk_terjual_aktual = float(request.form.get('produk_terjual_aktual') or 0)
            
            modal = float(request.form.get('modal_produk') or 0)
            fee = float(request.form.get('fee_shopee') or 0) / 100
            tambahan = float(request.form.get('biaya_tambahan') or 0)
            target_profit_pct = float(request.form.get('target_profit') or 0) / 100

            print(f"DEBUG Analisa Manual: Biaya Iklan={biaya_iklan_aktual}, Omzet={omzet_penjualan_aktual}, Terjual={produk_terjual_aktual}, Modal={modal}, Fee={fee}, Tambahan={tambahan}, Target Profit={target_profit_pct}")

            if not (biaya_iklan_aktual >= 0 and omzet_penjualan_aktual >= 0 and produk_terjual_aktual >= 0 and modal >= 0 and fee >= 0 and tambahan >= 0 and target_profit_pct >= 0):
                    raise ValueError("Pastikan semua input adalah angka positif yang valid.")

            # Calculate ROAS_aktual
            roas_aktual = omzet_penjualan_aktual / biaya_iklan_aktual if biaya_iklan_aktual > 0 else (0 if omzet_penjualan_aktual == 0 else np.inf)
            if not np.isfinite(roas_aktual): # Jika biaya iklan 0 dan omzet > 0, ROAS tak terhingga. Jika keduanya 0, ROAS 0.
                roas_aktual = 0.0 if (biaya_iklan_aktual == 0 and omzet_penjualan_aktual == 0) else 999999.0 # Representasikan tak terhingga dengan nilai besar

            # Calculate harga_jual_per_unit from provided data for internal use
            harga_jual_per_unit = omzet_penjualan_aktual / produk_terjual_aktual if produk_terjual_aktual > 0 else 0

            # NOTE: We are NOT directly passing harga_jual_per_unit to get_recommendation
            # because the 'Analisa Manual' form does not explicitly ask for 'Harga Jual per Unit'.
            # Instead, it's inferred from Omzet Penjualan and Produk Terjual.
            # get_recommendation will use this derived 'harga_jual_per_unit' by default,
            # unless a 'harga_jual_per_unit_input' is explicitly passed from recalculate_product.

            # Prepare a temporary row dictionary for get_recommendation
            temp_row_data_for_reco = {
                'produkId': 'Analisa Manual',
                'namaProduk': 'Produk Analisa Manual',
                'ROAS': roas_aktual, # Calculated ROAS
                'persentaseKlik': 0.01, # Default/dummy CTR, as it's not an input anymore but needed by function
                'biaya': biaya_iklan_aktual,
                'omzetPenjualan': omzet_penjualan_aktual,
                'produkTerjual': produk_terjual_aktual,
            }
            
            # Panggil get_recommendation dengan input dari form sebagai override.
            # harga_jual_per_unit_input di sini adalah nilai yang dihitung dari omzet/terjual.
            # Ini adalah tempat pemanggilan yang menyebabkan error, argumen kelima adalah harga_jual_per_unit_input
            # Yang sebelumnya tidak ada di definisi fungsi get_recommendation.
            analisa_reco, rekomendasi_aksi_reco, roas_target_optimal_reco, tag_warna_reco, detailed_explanation_reco, rekomendasi_modal_harian_val = get_recommendation(
                temp_row_data_for_reco, modal, fee, tambahan, target_profit_pct, harga_jual_per_unit_input=harga_jual_per_unit
            )

            # --- Calculate all relevant metrics for display ---
            biaya_fee_per_unit = harga_jual_per_unit * fee
            total_cost_per_unit_excluding_ads = modal + biaya_fee_per_unit + tambahan

            profit_kotor_per_unit = harga_jual_per_unit - total_cost_per_unit_excluding_ads
            roas_break_even_manual = 0
            if profit_kotor_per_unit > 0:
                roas_break_even_manual = harga_jual_per_unit / profit_kotor_per_unit
            else:
                roas_break_even_manual = np.inf # If gross profit is zero or negative, break-even ROAS is infinite

            # Ensure break-even ROAS doesn't exceed Shopee's cap for display
            display_roas_break_even_manual = min(roas_break_even_manual, SHOPEE_ROAS_CAP) if np.isfinite(roas_break_even_manual) else "Tak Terhingga"

            # Calculate Profit Bersih Aktual
            total_modal_produk_aktual = modal * produk_terjual_aktual
            total_fee_shopee_aktual = (harga_jual_per_unit * fee) * produk_terjual_aktual
            total_biaya_tambahan_aktual = tambahan * produk_terjual_aktual
            
            total_biaya_operasional = total_modal_produk_aktual + total_fee_shopee_aktual + total_biaya_tambahan_aktual
            profit_bersih_aktual = omzet_penjualan_aktual - biaya_iklan_aktual - total_biaya_operasional
            
            target_profit_omzet_manual = omzet_penjualan_aktual * target_profit_pct
            status_profit_aktual_text = "✅ Sesuai Target" if profit_bersih_aktual >= target_profit_omzet_manual else "⚠️ Untung Tipis" if profit_bersih_aktual > 0 else "❌ Rugi"


            # --- Populate result_data for display in the HTML ---
            result_data['label_hasil'] = f"✨ Rekomendasi ROAS Anda: Target ROAS optimal: **{roas_target_optimal_reco}** untuk produk ini."

            result_data['label_keterangan'].append(f"Analisa: **{analisa_reco}**")
            result_data['label_keterangan'].append(f"Rekomendasi Aksi: **{rekomendasi_aksi_reco}**")
            result_data['label_keterangan'].append(f"ROAS Titik Impas Produk: **{display_roas_break_even_manual:,.2f}** (ROAS minimal yang harus dicapai agar tidak rugi.)")
            result_data['label_keterangan'].append(f"ROAS Aktual: **{roas_aktual:,.2f}**")
            result_data['label_keterangan'].append(f"Modal Harian Rekomendasi: **{rekomendasi_modal_harian_val}**")
            result_data['label_keterangan'].append(f"Estimasi Profit Bersih Aktual: **Rp{profit_bersih_aktual:,.0f}** ({status_profit_aktual_text})")
            result_data['label_keterangan'].append(f"Penjelasan Detail: {detailed_explanation_reco}")


            # Prepare table data (similar to Iklan Baru mode)
            table_headers = ("ROAS", "Biaya Iklan", "Omzet Penjualan", "Profit Total", "Trafik", "Keterangan")
            table_data = []

            # Simulate for a range of ROAS values around the actual and recommended ROAS
            sim_roas_values = []

            # Add actual ROAS to simulation points
            if np.isfinite(roas_aktual) and roas_aktual > 0 and roas_aktual <= SHOPEE_ROAS_CAP:
                sim_roas_values.append(roas_aktual)
            
            # Add recommended optimal ROAS if it's different and valid
            if np.isfinite(float(str(roas_target_optimal_reco).replace(',', '.'))) and float(str(roas_target_optimal_reco).replace(',', '.')) > 0 and float(str(roas_target_optimal_reco).replace(',', '.')) <= SHOPEE_ROAS_CAP and abs(float(str(roas_target_optimal_reco).replace(',', '.')) - roas_aktual) > 0.05:
                sim_roas_values.append(float(str(roas_target_optimal_reco).replace(',', '.'))) # Convert back to float

            # Add break-even ROAS if different and valid
            if np.isfinite(roas_break_even_manual) and roas_break_even_manual > 0 and roas_break_even_manual <= SHOPEE_ROAS_CAP and abs(roas_break_even_manual - roas_aktual) > 0.05 and abs(roas_break_even_manual - float(str(roas_target_optimal_reco).replace(',', '.')) if np.isfinite(float(str(roas_target_optimal_reco).replace(',', '.'))) else 0) > 0.05 :
                   sim_roas_values.append(roas_break_even_manual)
            elif roas_break_even_manual <= 0 and 0.01 not in sim_roas_values: # If product is always profitable, add a very small ROAS for comparison
                sim_roas_values.append(0.01)

            # Add a few points around actual ROAS for context
            if np.isfinite(roas_aktual) and roas_aktual > 0:
                sim_roas_values.append(min(SHOPEE_ROAS_CAP, roas_aktual * 1.2)) # 20% higher
                sim_roas_values.append(max(1.0, roas_aktual * 0.8)) # 20% lower
                if roas_aktual > 20: # Add a point much lower if ROAS is high
                    sim_roas_values.append(max(1.0, roas_aktual - 10.0))
                if roas_aktual < 10: # Add a point much higher if ROAS is low
                    sim_roas_values.append(min(SHOPEE_ROAS_CAP, roas_aktual + 10.0))

            # Ensure minimal SHOPEE_MIN_DAILY_BUDGET for modal harian recommendation
            # This is implicitly handled by get_recommendation's modal_harian_rekomendasi_val
            
            sim_roas_values = sorted(list(set([round(x, 2) for x in sim_roas_values if x > 0])), reverse=True)
            
            # Limit to max 5-7 rows
            if len(sim_roas_values) > 7:
                # Prioritize actual, target optimal, break-even, then distribute the rest
                final_sim_roas_values = []
                if np.isfinite(roas_aktual) and roas_aktual > 0:
                    final_sim_roas_values.append(roas_aktual)
                if np.isfinite(float(str(roas_target_optimal_reco).replace(',', '.'))):
                    final_sim_roas_values.append(float(str(roas_target_optimal_reco).replace(',', '.')))
                if np.isfinite(roas_break_even_manual) and roas_break_even_manual > 0:
                    final_sim_roas_values.append(roas_break_even_manual)
                
                # Add a few more from the sorted list, avoiding duplicates
                for val in sim_roas_values:
                    if val not in final_sim_roas_values and len(final_sim_roas_values) < 7:
                        final_sim_roas_values.append(val)
                sim_roas_values = sorted(list(set([round(x,2) for x in final_sim_roas_values if x > 0])), reverse=True) # Ensure unique, sorted, positive
            
            # Generate table data
            for r_val in sim_roas_values:
                # For manual mode's simulation table, we need to recalculate based on the *current*
                # harga_jual_per_unit, modal, fee, and tambahan that the user just provided.
                # The sim_base_units for table will be the produk_terjual_aktual.
                table_data.append(calculate_row_for_simulation(
                    r_val, harga_jual_per_unit, produk_terjual_aktual, total_cost_per_unit_excluding_ads, target_profit_pct, roas_break_even_manual
                ))
            
            result_data['table_headers'] = table_headers
            result_data['table_data'] = table_data
            flash_messages.append({'category': 'success', 'message': 'Analisis Manual berhasil!'})


        except ValueError as e:
            flash_messages.append({'category': 'danger', 'message': f"Isi semua kolom dengan angka yang valid dan periksa nilai input. Detail: {e}"})
            print(f"DEBUG: ValueError in mode 'jalan': {e}")
        except Exception as e:
            flash_messages.append({'category': 'danger', 'message': f"Terjadi kesalahan saat menghitung mode Analisa Manual: {e}"})
            print(f"DEBUG: General Exception in mode 'jalan': {e}")

    elif mode == 'csv':
        if 'csv_file' not in request.files:
            flash_messages.append({'category': 'danger', 'message': 'Tidak ada file CSV yang diunggah.'})
        else:
            csv_file = request.files['csv_file']
            if csv_file.filename == '':
                flash_messages.append({'category': 'danger', 'message': 'Nama file kosong.'})
            elif csv_file:
                try:
                    file_content = io.StringIO(csv_file.stream.read().decode('utf-8'))

                    column_names = [
                        'Urutan', 'Nama Iklan', 'Status', 'Kode Produk', 'Mode Bidding', 'Penempatan Iklan', 'Tanggal Mulai',
                        'Tanggal Selesai', 'Dilihat', 'Jumlah Klik', 'Persentase Klik', 'Konversi', 'Konversi Langsung',
                        'Tingkat konversi', 'Tingkat Konversi Langsung', 'Biaya per Konversi', 'Biaya per Konversi Langsung',
                        'Produk Terjual', 'Terjual Langsung', 'Omzet Penjualan', 'Penjualan Langsung (GMV Langsung)',
                        'Biaya', 'Efektifitas Iklan', 'Efektivitas Langsung', 'Persentase Biaya Iklan terhadap Penjualan dari Iklan (ACOS)',
                        'Persentase Biaya Iklan terhadap Penjualan dari Iklan Langsung (ACOS Langsung)'
                    ]
                    
                    try:
                        df = pd.read_csv(file_content, skiprows=11, header=None, names=column_names, sep=',', skipinitialspace=True)
                    except Exception:
                        file_content.seek(0)
                        try:
                            df = pd.read_csv(file_content, skiprows=11, header=None, names=column_names, sep=';', skipinitialspace=True)
                        except Exception as e_csv:
                            raise ValueError(f"Gagal membaca file CSV. Pastikan file adalah CSV dengan pemisah koma atau titik koma. Detail: {e_csv}")

                    required_cols = ['Nama Iklan', 'Kode Produk', 'Biaya', 'Omzet Penjualan', 'Persentase Klik', 'Status', 'Produk Terjual']
                    missing_cols = [col for col in required_cols if col not in df.columns]
                    if missing_cols:
                        raise ValueError(f"File CSV tidak memiliki kolom yang dibutuhkan: {', '.join(missing_cols)}. Harap pastikan format Shopee yang benar.")

                    # Mengganti nama kolom agar konsisten dengan JavaScript (camelCase)
                    df.rename(columns={
                        'Nama Iklan': 'namaProduk',
                        'Kode Produk': 'produkId',
                        'Biaya': 'biaya',
                        'Omzet Penjualan': 'omzetPenjualan',
                        'Produk Terjual': 'produkTerjual',
                        'Persentase Klik': 'persentaseKlik',
                    }, inplace=True)

                    df['produkId'] = df['produkId'].astype(str)

                    # --- REVISED CLEANING LOGIC FOR NUMERIC COLUMNS ---
                    # Gunakan nama kolom yang sudah di-camelCase-kan untuk proses cleaning
                    for col_name in ['biaya', 'omzetPenjualan', 'persentaseKlik', 'produkTerjual']:
                        if col_name in df.columns:
                            # Pastikan nilai adalah string sebelum .strip()
                            cleaned_series = df[col_name].astype(str).str.strip()
                            cleaned_series = cleaned_series.str.replace('Rp', '', regex=False)
                            cleaned_series = cleaned_series.str.replace('%', '', regex=False)
                            cleaned_series = cleaned_series.str.replace(',', '', regex=False) # Remove thousands separator
                            
                            # Coba konversi ke numerik. errors='coerce' akan mengubah yang gagal jadi NaN
                            df[col_name] = pd.to_numeric(cleaned_series, errors='coerce')
                            
                            # Jika hasilnya NaN, ubah menjadi 0 agar tidak menyebabkan masalah isfinite dalam perhitungan
                            df[col_name] = df[col_name].fillna(0)

                            if col_name == 'persentaseKlik':
                                df[col_name] = df[col_name].div(100)
                        else:
                            df[col_name] = 0 # Jika kolom tidak ada, set ke 0
                    # --- END REVISED CLEANING LOGIC ---

                    # Debug prints (pertahankan untuk melacak)
                    print(f"\n--- DEBUG: After numeric conversion and before NaN to None conversion ---")
                    print(df[['produkId', 'biaya', 'omzetPenjualan', 'produkTerjual']].to_string())
                    print(f"Dtype 'omzetPenjualan' before NaN to None: {df['omzetPenjualan'].dtype}")
                    
                    # Convert NaN (dari coerse) ke None untuk JSON serialization
                    # Penting: Lakukan fillna(0) dulu untuk perhitungan, baru ubah ke None untuk JSON display
                    df_for_calc = df.copy() # Buat salinan untuk perhitungan

                    df_for_calc['ROAS'] = np.where(
                        (df_for_calc['biaya'] > 0), # Hanya perlu cek > 0 karena sudah difillna(0)
                        df_for_calc['omzetPenjualan'] / df_for_calc['biaya'],
                        0
                    )
                    df_for_calc['ROAS'] = df_for_calc['ROAS'].replace([np.inf, -np.inf], np.nan)
                    df_for_calc['ROAS'] = df_for_calc['ROAS'].where(pd.notnull, None) # Kembali ubah NaN jadi None untuk JSON
                    
                    df_to_analyze = df_for_calc[df_for_calc['Status'] == 'Berjalan'].copy()

                    if df_to_analyze.empty:
                        flash_messages.append({'category': 'info', 'message': 'Tidak ada data iklan "Berjalan" yang valid ditemukan dalam file CSV untuk dianalisis.'})
                        result_data['label_hasil'] = "Analisa Selesai. Tidak ada data iklan 'Berjalan' ditemukan."
                        result_data['label_keterangan'].append("Pastikan file CSV Anda berisi iklan dengan status 'Berjalan'.")
                    else:
                        print(f"\n--- DEBUG: Rows for get_recommendation ---")
                        # get_recommendation akan dipanggil tanpa override, jadi dia akan pakai default assumptions
                        # Default assumptions for modal, fee, additional costs will be used here.
                        rekomendasi = df_to_analyze.apply(
                            lambda row: get_recommendation(row), # Cukup panggil dengan row, parameter override lainnya None
                            axis=1, result_type='expand'
                        )
                        # Nama kolom hasil rekomendasi juga diubah ke camelCase
                        rekomendasi.columns = [
                            'analisa', 'rekomendasiAksi', 'roasTargetOptimal',
                            'tagWarna', 'detailedExplanation', 'rekomendasiModalHarian'
                        ]

                        df_to_analyze = pd.concat([df_to_analyze, rekomendasi], axis=1)

                        tag_order_map = {'sangat_baik': 3, 'cukup_baik': 2, 'boncos': 1, 'netral': 0, 'default': 0}
                        df_to_analyze['Tag_Order_Score'] = df_to_analyze['tagWarna'].map(tag_order_map).fillna(0)

                        # Pastikan kolom 'biaya' juga di-fillna(0) sebelum sort_score
                        df_to_analyze['Sort_Score'] = np.where(
                            (df_to_analyze['ROAS'].notnull()) & (df_to_analyze['ROAS'] > 0),
                            df_to_analyze['ROAS'],
                            -df_to_analyze['biaya'].fillna(0)
                        )
                        df_to_analyze['Sort_Score'] = df_to_analyze['Sort_Score'].where(pd.notnull, -999999999)

                        df_to_analyze = df_to_analyze.sort_values(
                            by=['Tag_Order_Score', 'Sort_Score'],
                            ascending=[False, False]
                        )

                        # Mengambil data untuk JSON. Gunakan nama kolom yang sudah di-camelCase-kan
                        products_data = df_to_analyze[[
                            'namaProduk', 'produkId', 'biaya', 'omzetPenjualan', 'ROAS',
                            'analisa', 'rekomendasiAksi', 'roasTargetOptimal', 'tagWarna',
                            'persentaseKlik', 'produkTerjual', 'detailedExplanation',
                            'rekomendasiModalHarian'
                        ]].to_dict(orient='records')
                        
                        print(f"\n--- DEBUG: products_data before JSONIFY ---")
                        # Hapus baris debug yang bermasalah (target_product_id)
                        # for p_data in products_data:
                        #      produk_id_dbg = p_data.get('produkId')
                        #      if produk_id_dbg == target_product_id:
                        #          print(f"Product ID: {produk_id_dbg}")


                        result_data['label_hasil'] = f"Analisa Selesai. Ditemukan {len(df_to_analyze)} iklan 'Berjalan' yang telah diurutkan."
                        # Menambahkan pesan keterangan ke label_keterangan sebagai list
                        result_data['label_keterangan'] = [
                            "Berikut adalah daftar produk hasil analisa (diurutkan berdasarkan performa iklan):",
                            "Untuk perhitungan ROAS Rekomendasi & Modal Harian Rekomendasi yang lebih akurat, silakan klik tombol \"Lihat Detail\" lalu \"Hitung Ulang Produk Ini\" di popup detail produk."
                        ]
                        result_data['products_data'] = products_data

                        # Simpan DataFrame yang sudah dianalisis dan di-camelCase-kan ke sesi
                        # agar bisa diakses oleh fungsi recalculate_product
                        # Penting: Pastikan ini adalah df_to_analyze yang sudah lengkap dengan hasil rekomendasi
                        session['analyzed_df_json'] = df_to_analyze.to_json(orient='records')
                        flash_messages.append({'category': 'success', 'message': 'File CSV berhasil diunggah dan dianalisis!'})

                except Exception as e:
                    print(f"Error processing CSV: {e}")
                    flash_messages.append({'category': 'danger', 'message': f"Gagal memproses file CSV. Pastikan format file benar atau coba dengan file lain. Detail: {e}"})
    
    # Hanya untuk mode 'analyze' awal, bukan untuk '/recalculate_product'
    if request.path == url_for('calculator_roas.analyze'):
        session['calculator_roas_mode'] = mode
        session['calculator_roas_result'] = result_data

        print(f"\n--- Sending JSON response for mode: {mode} ---")
        print(f"Flash messages: {flash_messages}")
        return jsonify({
            'mode': mode,
            'result': result_data,
            'flash_messages': flash_messages
        })
    # else, for recalculate_product, response is handled in that route directly


# --- Endpoint for Recalculate Single Product (Updated for new flow) ---
@bp.route('/recalculate_product', methods=['POST'])
@login_required
def recalculate_product():
    print("\n--- Received recalculate_product request ---")
    flash_messages = []
    try:
        produk_id = request.form.get('produkId')
        modal_input = float(request.form.get('modal') or 0)
        harga_jual_input = float(request.form.get('harga_jual') or 0) # This is the 'Harga Jual' from recalculate modal, directly given
        fee_input = float(request.form.get('fee') or 0) / 100
        tambahan_input = float(request.form.get('tambahan') or 0)
        target_profit_pct_input = float(request.form.get('target_profit') or 0) / 100

        # Get original ad data from form (passed as hidden fields from front-end)
        biaya_iklan_aktual = float(request.form.get('biayaIklanAktual') or 0)
        omzet_penjualan_aktual = float(request.form.get('omzetPenjualanAktual') or 0)
        produk_terjual_aktual = float(request.form.get('produkTerjualAktual') or 0)
        roas_aktual = float(request.form.get('roasAktual') or 0)
        persentase_klik_aktual = float(request.form.get('persentaseKlikAktual') or 0)

        print(f"DEBUG: Recalculate for Produk ID: {produk_id}")
        print(f"  Inputs: Modal={modal_input}, HargaJual={harga_jual_input}, Fee={fee_input}, Tambahan={tambahan_input}, TargetProfit={target_profit_pct_input}")
        print(f"  Original Ad Data: Biaya={biaya_iklan_aktual}, Omzet={omzet_penjualan_aktual}, Terjual={produk_terjual_aktual}, ROAS={roas_aktual}, CTR={persentase_klik_aktual}")

        # Prepare a temporary row dictionary for get_recommendation
        nama_produk_asli = "N/A"
        analyzed_df_json_from_session = session.get('analyzed_df_json')
        if analyzed_df_json_from_session:
            try:
                temp_df = pd.read_json(io.StringIO(analyzed_df_json_from_session), orient='records')
                original_row = temp_df[temp_df['produkId'] == produk_id]
                if not original_row.empty:
                    nama_produk_asli = original_row['namaProduk'].iloc[0]
            except Exception as e:
                print(f"WARNING: Gagal membaca nama produk dari sesi untuk ID {produk_id}: {e}")

        temp_row_for_reco_data = {
            'produkId': produk_id,
            'namaProduk': nama_produk_asli, # Gunakan nama asli dari sesi
            'ROAS': roas_aktual,
            'persentaseKlik': persentase_klik_aktual,
            'biaya': biaya_iklan_aktual,
            'omzetPenjualan': omzet_penjualan_aktual,
            'produkTerjual': produk_terjual_aktual,
        }
        
        # Panggil get_recommendation dengan data override
        # Urutan argumen: row_data, modal_produk_input, fee_shopee_input, biaya_tambahan_input, target_profit_pct_input, harga_jual_per_unit_input
        analisa_reco, rekomendasi_aksi_reco, roas_target_optimal_reco, tag_warna_reco, detailed_explanation_reco, rekomendasi_modal_harian_val = \
            get_recommendation(
                temp_row_for_reco_data, 
                modal_produk_input, 
                fee_input, 
                tambahan_input, 
                target_profit_pct_input, 
                harga_jual_per_unit_input # Pass this explicitly as the 6th argument
            )

        # Siapkan data produk yang diperbarui untuk dikembalikan ke frontend popup
        # Ini adalah data yang akan ditampilkan di popup, tidak mengubah tabel utama lagi
        recalculated_display_data = {
            'produkId': produk_id,
            'namaProduk': nama_produk_asli, # Pastikan nama produk ada di data yang dikembalikan
            'biayaIklanAktual': f"Rp{biaya_iklan_aktual:,.0f}",
            'omzetPenjualanAktual': f"Rp{omzet_penjualan_aktual:,.0f}",
            'produkTerjualAktual': f"{int(produk_terjual_aktual):,} Unit",
            'roasAktual': f"{roas_aktual:,.2f}",
            'analisa': analisa_reco,
            'rekomendasiAksi': rekomendasi_aksi_reco,
            'roasTargetOptimal': roas_target_optimal_reco,
            'modalHarianRekomendasi': rekomendasi_modal_harian_val,
            'detailedExplanation': detailed_explanation_reco,
            'tagWarna': tag_warna_reco # Tambahkan tagWarna untuk styling di JS
        }
        
        flash_messages.append({'category': 'success', 'message': f"Produk {produk_id} berhasil dihitung ulang."})
        return jsonify({
            'recalculated_data_for_popup': recalculated_display_data,
            'flash_messages': flash_messages
        })

    except ValueError as e:
        flash_messages.append({'category': 'danger', 'message': f"Isi semua kolom dengan angka yang valid! Detail: {e}"})
        print(f"DEBUG: ValueError in /recalculate_product: {e}")
        return jsonify({
            'recalculated_data_for_popup': None,
            'flash_messages': flash_messages
        }), 400
    except Exception as e:
        flash_messages.append({'category': 'danger', 'message': f"Terjadi kesalahan saat menghitung ulang produk: {e}"})
        print(f"DEBUG: General Exception in /recalculate_product: {e}")
        return jsonify({
            'recalculated_data_for_popup': None,
            'flash_messages': flash_messages
        }), 500


# Helper function to calculate a single row for the simulation table
def calculate_row_for_simulation(
    roas_value, harga_jual, sim_base_units, total_cost_per_unit_excluding_ads, target_profit_pct, roas_break_even,
    biaya_iklan_fixed=None
):
    if not isinstance(roas_value, (int, float)):
        roas_value = 1.0
    roas_value = float(roas_value)

    if biaya_iklan_fixed is not None:
        biaya_iklan_sim = float(biaya_iklan_fixed)
        omzet_simulasi = biaya_iklan_sim * roas_value
    else:
        omzet_simulasi = harga_jual * sim_base_units
        # Handle division by zero for roas_value
        biaya_iklan_sim = omzet_simulasi / roas_value if roas_value > 0 else (0 if omzet_simulasi == 0 else np.inf)

    if not np.isfinite(biaya_iklan_sim):
        profit_total_sim = float('-inf')
        status_text = "❌ Rugi Tak Terbatas"
        row_color_tag = 'boncos'
        trafik = "Sangat Kencang (Rugi Besar)"
    else:
        # Calculate profit total correctly: Omzet - Biaya Iklan - Total Biaya Pokok (modal + fee + tambahan)
        profit_total_sim = omzet_simulasi - biaya_iklan_sim - (total_cost_per_unit_excluding_ads * sim_base_units)
        
        target_profit_omzet_for_row = omzet_simulasi * target_profit_pct
        is_profit_positive_for_row = profit_total_sim > 0

        status_text = ""
        if profit_total_sim >= target_profit_omzet_for_row:
            status_text = "✅ Sesuai Target"
        elif is_profit_positive_for_row:
            status_text = "⚠️ Untung Tipis"
        else:
            status_text = "❌ Rugi"
        
        row_color_tag = get_row_color_tag(profit_total_sim, target_profit_omzet_for_row, is_profit_positive_for_row)
        
        trafik = ""
        if roas_value > SHOPEE_ROAS_CAP + 0.01:
            trafik = "Tidak Dapat Diatur"
        elif roas_break_even > 0:
            if roas_value >= (roas_break_even * 2.0):
                trafik = "Sangat Rendah (Sangat Efisien)"
            elif roas_value >= roas_break_even:
                trafik = "Rendah (Efisien)"
            elif roas_value >= (roas_break_even * 0.5):
                trafik = "Sedang (Kurang Efisien)"
            elif roas_value > 0:
                trafik = "Kencang (Rugi)"
            else:
                trafik = "Sangat Kencang (Rugi Besar)"
        else: # Case where product is profitable even without ads (ROAS break-even <= 0)
            if roas_value >= 10.0:
                trafik = "Sangat Rendah (Sangat Efisien)"
            elif roas_value > 0:
                trafik = "Rendah (Efisien)"
            else:
                trafik = "Sangat Kencang (Rugi Besar)"

    formatted_roas_value = f"{roas_value:,.2f}" if np.isfinite(roas_value) else "N/A"
    formatted_biaya_iklan_sim = f"Rp{biaya_iklan_sim:,.0f}" if np.isfinite(biaya_iklan_sim) else "N/A"
    formatted_omzet_simulasi = f"Rp{omzet_simulasi:,.0f}" if np.isfinite(omzet_simulasi) else "N/A"
    formatted_profit_total_sim = f"Rp{profit_total_sim:,.0f}" if np.isfinite(profit_total_sim) else "N/A"
    
    if np.isfinite(profit_total_sim) and profit_total_sim < 0:
        formatted_profit_total_sim = f"-Rp{abs(profit_total_sim):,.0f}"
    elif not np.isfinite(profit_total_sim):
        formatted_profit_total_sim = "Rugi Tak Terbatas" if profit_total_sim == float('-inf') else "N/A"


    return [
        formatted_roas_value,
        formatted_biaya_iklan_sim,
        formatted_omzet_simulasi,
        formatted_profit_total_sim,
        trafik,
        status_text,
        row_color_tag
    ]