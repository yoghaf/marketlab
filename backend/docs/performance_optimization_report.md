# MarketLab Performance Optimization

Tanggal audit dan deploy: 2026-07-22

## Tujuan

Mengurangi beban CPU, query SQLite, penulisan disk, latency API, dan kerja riset berulang tanpa mengubah rule Signal Factory, classifier, perhitungan TP/SL, outcome, atau data historis.

## Ringkasan Sebelum dan Sesudah

| Area | Sebelum | Sesudah di VPS | Dampak terukur |
|---|---:|---:|---:|
| `/api/data-health` | 28.514 detik pada benchmark pre-deploy; historical peak sekitar 55 detik; sekitar 525 SQL | 4.606-7.612 detik cold, 0.022 detik cache hit; direct benchmark 34 SQL | cold HTTP turun sekitar 73-84% dari benchmark pre-deploy; SQL turun sekitar 93.5% |
| `/api/scanner/live` | 9.135 detik pada benchmark pre-deploy; historical peak sekitar 36 detik; outcome N+1 | 0.396 detik HTTP; 0.384 detik direct; 10 SQL | HTTP turun sekitar 95.7% dari benchmark pre-deploy |
| Scanner correctness | latest/outcome dibaca per-row | latest actual/latest usable terindeks, outcomes batch | 20 row, duplicate symbol 0, seluruh `not_entry_signal=true` |
| Fast pipeline | rich fetch berada di jalur kritis; catch-up berulang; lock DB dapat menggagalkan cycle | rich collector proses terpisah; normal 3 window, catch-up maksimal 12; commit per symbol/payload | cycle catch-up sukses 11m20s; steady-state sukses 8m14s |
| SQLite writer | transaksi dapat tetap terbuka selama request Binance berikutnya | commit setelah payload/symbol dan bounded retry | tidak ada `database is locked`, traceback, atau `PendingRollbackError` baru pada cycle tervalidasi |
| Aggregate rerun | row existing selalu disentuh | row identik tidak ditulis ulang | mengurangi write amplification dan perubahan `updated_at` yang tidak bermakna |
| Rich collection | bagian dari fast pipeline 15m | PM2 `marketlab-rich-loop`, cadence 30 menit | latency jaringan/rate-limit rich tidak lagi menahan feature/classifier |
| Snapshot collector | production sudah 300 detik | tetap 300 detik | tidak dilonggarkan lagi; masih memenuhi freshness policy |
| Snapshot performance | default + snapshot riset 1h besar dihitung bersama tiap fast cycle | default live tiap fast cycle; snapshot 1h hanya pada cadence optimasi 6 jam | pekerjaan 1h berat tidak lagi masuk setiap cycle 15m |
| Full research | mengulang Signal Factory, logger, performance, dan V3 yang baru selesai | cadence 6 jam hanya menjalankan snapshot 1h + artifact optimization | satu rerun core penuh per 6 jam dihapus |
| V3 shadow | ikut core setiap 15 menit; sekitar 60-68 detik per run | runner terpisah setiap 1 jam | frekuensi turun 75%; sekitar 3 run atau 180-204 detik kerja per jam dihapus tanpa kehilangan histori |
| Scheduler | marker ditulis saat cycle selesai dan check tiap 5 menit | marker memakai waktu mulai cycle dan check ringan tiap 2 menit | target start steady-state sekitar 15-16 menit, tanpa overlap |
| Frontend polling | refresh tetap berjalan saat tab tersembunyi | minimum 60 detik dan pause saat hidden | polling hidden turun 100% |

Angka API diambil dari VPS production database sekitar 10.4 GB. Latency cold dapat berubah mengikuti contention CPU host, aktivitas collector, dan page cache SQLite.

## Perubahan Teknis

1. Data Health memakai query set-based, covering index, dan cache in-process 30 detik dengan response shape lama tetap dipertahankan.
2. Live Scanner memakai index latest-per-symbol dan batch outcome, tanpa N+1 query.
3. Alembic `0017` menambah index classifier; `0018` menambah covering index summary untuk context, candidate, rich alignment, dan market state.
4. `JsonRunLock` dipakai bersama oleh runner kline, aggregation, rich, snapshot, dan research; stale/malformed lock dipulihkan secara ownership-safe.
5. Kline, snapshot/current, rich source, dan aggregation melepas transaksi SQLite setelah unit kerja kecil, bukan menahan writer lock selama network wait berikutnya.
6. Aggregator melewati update jika seluruh nilai row existing sudah sama.
7. Rich futures collector dipindahkan ke `marketlab-rich-loop` dengan cadence 1.800 detik.
8. Fast pipeline mengikuti cadence 15m, sedangkan maintenance 4h dan 24h mengikuti timeframe native dan tetap bounded.
9. Signal performance snapshot dibagi menjadi scope `default`, `one-hour`, dan `all`; manual runner tetap kompatibel dengan default `all`.
10. Research `light` menjalankan core current-state; research `optimization` hanya menjalankan snapshot 1h dan artifact optimization. Mode `full` manual tetap tersedia.
11. PM2 logrotate diubah dari retain 30 tanpa kompresi menjadi retain 7 dengan kompresi.
12. V3 shadow dikeluarkan dari cycle `light` 15 menit dan dijalankan melalui mode `shadow` setiap 1 jam. Runner tetap membaca ulang seluruh riwayat sehingga event di antara checkpoint tidak hilang.
13. Ollama/Gemma 4 dan Redis idle yang tidak direferensikan runtime MarketLab dinonaktifkan. Model, runtime Ollama, log PM2 lama, journal lama, dan cache build/package dibersihkan.

## Validasi Produksi

| Check | Hasil |
|---|---|
| Commit optimasi runtime akhir | `501a26b` |
| Alembic head | `0018_data_health_summary_indexes` |
| Backend tests | 214 passed |
| Frontend production build | sukses pada perubahan frontend terakhir; tahap final ini tidak mengubah frontend |
| PM2 | backend, frontend, kline, snapshot, research, dan rich loop online |
| Fast catch-up | SUCCESS; 12 window; selesai 04:16:55 UTC |
| 4h maintenance | SUCCESS; selesai 04:19:20 UTC |
| 24h maintenance | SUCCESS; selesai 04:25:00 UTC |
| Optimization-only cycle | SUCCESS; snapshot 1h 87 detik; artifacts 238 detik; tidak mengulang core |
| Fast steady-state | SUCCESS; 3 window; 04:36:21-04:44:35 UTC |
| Fast steady-state + start marker | SUCCESS; 3 window; 04:51:31-04:58:23 UTC; marker tersimpan 04:51:31 UTC |
| Lock/error scan | tidak ada error SQLite/rollback/traceback baru sejak cycle perbaikan |
| API health | HTTP 200, sekitar 0.045 detik |
| API scanner | HTTP 200, sekitar 0.396 detik |
| API data health | HTTP 200, cold teramati 4.606-7.612 detik, cache sekitar 0.022 detik |
| Frontend | `/scanner` teramati 1.299-1.505 detik; `/signal-performance` sekitar 0.303 detik |

## Resource VPS

| Resource | Kondisi akhir audit |
|---|---:|
| Disk root | 39 GB total; sebelum cleanup 1.6 GB free/96% used; sesudah cleanup 18 GB free/56% used |
| Database | sekitar 9.8 GB |
| PM2 logs | sekitar 1.0 GB sebelum cleanup; 350 MB sesudah log lebih lama dari 7 hari dibuang |
| Memory | sekitar 4.8 GB available dari 5.8 GB pada final check |
| Swap | tidak tersedia |

Cleanup membebaskan sekitar 16.4 GB tanpa menghapus database atau data historis. Sumber terbesar adalah model/runtime Ollama yang tidak dipakai MarketLab (sekitar 13.7 GB), disusul log PM2 lama, journal, dan cache. Pertumbuhan database tetap perlu dipantau.

## Residual Work

1. Overview SSR masih sekitar 7 detik saat cold karena menunggu Data Health, Collectors, Aggregation, dan Scanner sekaligus. Ini bukan blocker collector, tetapi kandidat optimasi frontend/cache berikutnya.
2. Default signal performance snapshot masih membutuhkan sekitar 155 detik untuk mengevaluasi hingga 500 signal. Sudah dikeluarkan dari endpoint request, tetapi incremental snapshot dapat diteliti kemudian.
3. VPS hanya 1 vCPU. Sampling `vmstat` menunjukkan CPU steal berubah-ubah antara sekitar 6% dan 52%; bagian ini adalah contention host/provider dan tidak dapat dihilangkan oleh optimasi aplikasi. VPS 2 vCPU dedicated menjadi perbaikan berikutnya jika latency harus konsisten.
4. Instalasi Hermes sekitar 1.5 GB tidak memiliki proses aktif, tetapi sengaja belum dihapus karena kepemilikannya belum cukup jelas dan tidak memengaruhi CPU saat ini.

## Guardrail

- Tidak ada perubahan threshold Signal Factory.
- Tidak ada perubahan classifier, arah signal, TP/SL, RR, outcome, atau execution.
- Tidak ada direct Binance HTTP baru di luar `backend/app/services/binance_client.py`.
- Tidak ada data historis yang dihapus atau dipalsukan.
- Semua retry bounded; tidak ada loop retry tanpa batas.
