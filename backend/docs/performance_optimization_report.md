# MarketLab Performance Optimization

Tanggal audit: 2026-07-22

## Tujuan

Mengurangi beban CPU, query SQLite, penulisan disk, dan polling frontend tanpa mengubah rule Signal Factory, classifier, perhitungan TP/SL, atau data historis.

## Baseline VPS

| Area | Sebelum optimasi | Sesudah optimasi |
|---|---:|---:|
| `/api/data-health` | sekitar 55 detik; sekitar 525 SQL statement | Diukur setelah deploy |
| `/api/scanner/live` | sekitar 36 detik; scan candidate besar dan outcome N+1 | Diukur setelah deploy |
| Snapshot collector | setiap 60 detik | setiap 180 detik |
| Pipeline 15m/1h | dicek setiap 5 menit, hingga 12 window berulang | cadence 15 menit, 3 window normal, catch-up maksimal 12 |
| Pipeline 4h | dijalankan bersama long timeframe setiap jam | cadence native 4 jam |
| Pipeline 24h | dijalankan bersama long timeframe setiap jam | cadence native 24 jam |
| Full research | setiap 6 jam | tetap setiap 6 jam |
| Auto refresh umum | 30 detik, tetap aktif saat tab tersembunyi | minimal 60 detik, berhenti saat tab tersembunyi |
| Lock rusak/kosong | dapat membuat cycle terus skip atau gagal parse | recovery lock malformed dan ownership-safe release |

Baseline resource saat audit: VPS 1 vCPU dengan CPU steal tinggi, disk sekitar 96%, database sekitar 9.6 GB, dan log PM2 sekitar 1.1 GB. Karena CPU steal berasal dari host VPS, optimasi aplikasi mengurangi kerja MarketLab tetapi tidak dapat menghilangkan contention dari provider.

## Perubahan

1. Data Health memakai query set-based untuk snapshot terbaru dan rich-data freshness, plus cache 30 detik.
2. Live Scanner mengambil latest actual/latest usable per symbol melalui index gabungan dan memuat outcomes secara batch.
3. Index `symbol, window_close_time, window_open_time, id` ditambahkan ke tabel classifier melalui Alembic revision `0017`.
4. Research loop mengikuti cadence data: 15m, 4h, dan 24h dipisahkan; catch-up tetap bounded dan marker hanya maju saat pipeline sukses.
5. Snapshot collector diperlambat menjadi 180 detik. Ini masih di bawah batas freshness snapshot 5-10 menit.
6. Semua loop memakai `JsonRunLock` yang sama dengan pemeriksaan owner PID, recovery lock rusak, dan release yang tidak menghapus lock proses lain.
7. Frontend tidak melakukan refresh berkala saat tab tidak terlihat dan interval umum minimum menjadi 60 detik.
8. Script `benchmark_hot_paths.py` mengukur waktu, jumlah SQL statement, dan ukuran payload langsung terhadap database environment aktif.

## Dampak Teoretis

| Beban | Pengurangan yang diharapkan |
|---|---:|
| Siklus snapshot | sekitar 66.7% |
| Reprocessing fast pipeline steady-state | sekitar 75% atau lebih |
| Maintenance 4h | sekitar 75% dibanding hourly |
| Maintenance 24h | sekitar 95.8% dibanding hourly |
| Polling halaman umum yang terlihat | sekitar 50% |
| Polling halaman umum yang tersembunyi | 100% selama tab tersembunyi |
| Query Data Health per request cold | dari ratusan menjadi bounded puluhan |
| Query scanner DB path | latest rows dan outcome menjadi bounded batch queries |

Angka di atas adalah pengurangan pekerjaan terjadwal, bukan janji persentase CPU total. CPU total juga dipengaruhi traffic, ukuran database, SQLite contention, dan CPU steal VPS.

## Validasi Lokal

- Backend tests: 208 passed.
- Migration `0017`: fresh upgrade sukses dan upgrade ulang no-op.
- Frontend production build: sukses.
- Shell syntax research loop: sukses.
- Tidak ada perubahan rule Signal Factory, classifier, outcome, atau TP/SL.

## Validasi Produksi

Bagian ini diisi setelah deploy:

| Check | Hasil |
|---|---|
| Alembic head | Menunggu deploy |
| PM2 backend/frontend/research/snapshot | Menunggu deploy |
| Data Health benchmark cold/cache | Menunggu deploy |
| Scanner benchmark | Menunggu deploy |
| Snapshot cadence 180 detik | Menunggu deploy |
| Research cadence dan lock | Menunggu deploy |
| Disk/memory setelah deploy | Menunggu deploy |
