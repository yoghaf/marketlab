import Link from "next/link";

import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";

type PatchItem = {
  date: string;
  version: string;
  title: string;
  status: string;
  area: string;
  summary: string;
  changes: string[];
  impact: string;
  links: { href: string; label: string }[];
};

const patches: PatchItem[] = [
  {
    date: "2026-07-11",
    version: "LAB-31",
    title: "V3 Completion + Failure Analysis",
    status: "LIVE",
    area: "Signal research UI/API",
    summary: "Fokus riset dikembalikan ke V3: membedah V3_SHADOW_PASS yang TP vs SL sebelum ada V4 baru.",
    changes: [
      "Endpoint /api/v3-shadow/forward-log sekarang mengirim failure_analysis read-only untuk V3.",
      "Failure analysis membandingkan V3 TP vs SL berdasarkan evidence angka, filter, symbol, lane, dan latest TP/SL signal.",
      "Halaman /v3-forward-log sekarang menampilkan V3 failure analysis sebagai pusat riset lanjutan V3.",
      "Panel V4 di /signal-1h-review diberi label experimental/frozen agar tidak dianggap arah utama sebelum V3 selesai."
    ],
    impact: "Kita bisa melihat sisa penyakit V3 secara angka: filter mana yang masih menyumbang SL, evidence apa yang membedakan TP/SL, dan apakah V3 perlu refinement atau sudah cukup stabil untuk dipantau.",
    links: [
      { href: "/v3-forward-log", label: "V3 Forward Log" },
      { href: "/v3-shadow-lab", label: "V3 Shadow Lab" }
    ]
  },
  {
    date: "2026-07-11",
    version: "LAB-30",
    title: "1h V4 Shadow Forward Monitor",
    status: "LIVE",
    area: "Signal research UI/API",
    summary: "Menambahkan monitor V4 shadow read-only untuk melihat signal 1h mana yang lolos filter walk-forward tanpa mengubah rule live.",
    changes: [
      "Menambahkan endpoint /api/signal-candidates/one-hour-v4-shadow yang default membaca snapshot 1h.",
      "V4 shadow memilih filter dari hasil walk-forward 1h yang berstatus WF_PROMISING atau WF_REDUCES_DAMAGE.",
      "Halaman /signal-1h-review sekarang menampilkan filter V4 terpilih, pass/fail per stage, retention, delta realistic R, dan signal yang lolos shadow.",
      "V4 shadow status hanya label riset; tidak mengubah Signal Factory V2, scanner, TP/SL formula, outcome logic, atau execution."
    ],
    impact: "Kita bisa memantau apakah filter 1h yang lolos validation mulai stabil di signal terbaru sebelum dipertimbangkan sebagai rule baru.",
    links: [
      { href: "/signal-1h-review", label: "1h Review" },
      { href: "/signal-quality-lab?timeframe=1h", label: "Quality Lab 1h" }
    ]
  },
  {
    date: "2026-07-11",
    version: "LAB-29",
    title: "1h Walk-Forward Optimization Lab",
    status: "LIVE",
    area: "Signal research UI/API",
    summary: "Menambahkan walk-forward optimization read-only untuk menguji filter MID_LONG/MID_SHORT 1h dengan train 70% dan validation 30%.",
    changes: [
      "Menambahkan endpoint /api/signal-candidates/one-hour-walk-forward yang default membaca snapshot 1h agar tidak membebani backend.",
      "Walk-forward memakai closed 1h Signal, realistic R, chronological 70/30 split, dan filter specs existing.",
      "Halaman /signal-1h-review sekarang menampilkan lane walk-forward, train/validation realistic R, verdict filter, score, dan risk notes.",
      "Verdict seperti WF_PROMISING, WF_OVERFIT, WF_REDUCES_DAMAGE, dan WF_REJECT hanya untuk riset; tidak mengubah rule live atau execution."
    ],
    impact: "Kita bisa membedakan filter 1h yang benar-benar bertahan di data validation dari filter yang cuma bagus di data lama.",
    links: [
      { href: "/signal-1h-review", label: "1h Review" },
      { href: "/signal-quality-lab?timeframe=1h", label: "Quality Lab 1h" }
    ]
  },
  {
    date: "2026-07-11",
    version: "LAB-28",
    title: "1h Filter Candidate Study",
    status: "LIVE",
    area: "Signal research UI/API",
    summary: "Menambahkan studi filter 1h untuk membandingkan MID_LONG dan MID_SHORT dan mencari filter yang mungkin mengurangi SL atau memperbaiki R.",
    changes: [
      "Menambahkan endpoint read-only /api/signal-candidates/one-hour-filter-study untuk membaca filter candidate MID_LONG/MID_SHORT 1h.",
      "Halaman /signal-1h-review sekarang menampilkan lane status, baseline TP/SL/R, top filter candidate, action reason, dan risk notes.",
      "Action seperti PROMOTE_TO_SHADOW atau MONITOR_MORE hanya berarti pantauan riset, bukan rule live dan bukan execution.",
      "Tidak ada perubahan Signal Factory rule, scanner behavior, TP/SL formula, outcome logic, threshold, atau execution."
    ],
    impact: "Kita bisa mulai memilah filter 1h mana yang benar-benar mengurangi kerusakan dan mana yang harus ditolak, tanpa menebak threshold baru.",
    links: [
      { href: "/signal-1h-review", label: "1h Review" },
      { href: "/signal-quality-lab?timeframe=1h", label: "Quality Lab 1h" }
    ]
  },
  {
    date: "2026-07-11",
    version: "LAB-27",
    title: "1h TP/SL Cause Analysis",
    status: "LIVE",
    area: "Signal research UI",
    summary: "Menambahkan panel penyebab TP/SL di halaman 1h Review untuk membedah apakah long atau short 1h yang lebih sering gagal dan evidence apa yang membedakan hasilnya.",
    changes: [
      "Halaman /signal-1h-review sekarang menampilkan breakdown Long vs Short, Stage + arah, evidence TP vs SL, dan symbol penyumbang SL.",
      "Evidence yang dibandingkan mencakup price return, volume vs average, range/ATR, taker buy/sell, OI, funding, spread, long/short ratio, top trader ratio, core score, dan evidence score.",
      "Panel ini membaca snapshot performance 1h yang sudah ada sehingga tidak menambah rule, threshold, scanner behavior, TP/SL formula, outcome logic, atau execution.",
      "Tujuannya membantu riset penyebab SL/TP 1h sebelum ada perubahan definisi signal."
    ],
    impact: "Kita bisa melihat apakah masalah 1h lebih berat di long atau short, symbol mana yang sering merusak, dan evidence mana yang benar-benar berbeda antara hasil target referensi dan stop referensi.",
    links: [
      { href: "/signal-1h-review", label: "1h Review" },
      { href: "/signal-quality-lab", label: "Signal Quality Lab" }
    ]
  },
  {
    date: "2026-07-11",
    version: "LAB-26",
    title: "1h Signal Review Mode",
    status: "LIVE",
    area: "Signal research UI",
    summary: "Menambahkan halaman khusus untuk membaca Signal timeframe 1h tanpa tercampur noise 15m.",
    changes: [
      "Halaman /signal-1h-review menampilkan total R, realistic R, TP/SL, winrate, open signal, stage performance, symbol quality, dan latest closed 1h signals.",
      "Snapshot Signal History sekarang juga menyimpan performance dan forward integrity khusus 1h agar halaman 1h Review tidak cold-load berat.",
      "Menu utama menambahkan 1h Review, dan Signal History diberi shortcut ke halaman ini.",
      "Halaman ini read-only untuk riset kualitas timeframe; tidak mengubah Signal Factory rule, scanner behavior, TP/SL formula, threshold, outcome logic, atau execution."
    ],
    impact: "Kita bisa mengevaluasi apakah 1h layak menjadi fokus signal utama, sementara 15m tetap dipakai sebagai radar/noise context.",
    links: [
      { href: "/signal-1h-review", label: "1h Review" },
      { href: "/signal-performance", label: "Signal History" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-25",
    title: "Signal History Snapshot Read Model",
    status: "LIVE",
    area: "UI/API stability",
    summary: "Signal History default sekarang membaca snapshot yang dibuat research-loop, bukan menghitung ulang semua posisi paper saat halaman dibuka.",
    changes: [
      "Menambahkan artifact Signal Performance berisi closed-only paper result default untuk halaman Signal History.",
      "Menambahkan artifact Forward Integrity berisi audit open/waiting/stale default.",
      "Research-loop sekarang membuat snapshot ini setelah signal forward return logger berjalan.",
      "Endpoint Signal History otomatis memakai snapshot untuk filter default; filter audit khusus tetap bisa fallback ke live compute.",
      "Tidak ada perubahan Signal Factory rule, scanner behavior, TP/SL formula, threshold, outcome logic, atau execution."
    ],
    impact: "Cold-load Signal History tidak lagi perlu komputasi berat setiap dibuka, sehingga risiko 500/504 dan halaman kosong turun signifikan.",
    links: [
      { href: "/signal-performance", label: "Signal History" },
      { href: "/scanner", label: "Radar" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-24",
    title: "Scanner API Timeout Guard",
    status: "LIVE",
    area: "UI/API stability",
    summary: "Mengurangi risiko Radar dan Signal History kosong karena backend API terlalu lama menghitung ulang data live.",
    changes: [
      "Radar default tidak lagi menghitung V3 shadow filter map berat di setiap request; V3 audit tetap dibaca dari halaman V3 Forward Log.",
      "Endpoint Scanner diberi cache pendek 30 detik agar auto-refresh dan klik berulang tidak menumpuk komputasi yang sama.",
      "Endpoint Forward Integrity di Signal History juga diberi cache pendek 30 detik.",
      "Menambahkan opsi backend include_v3_shadow untuk kebutuhan audit khusus tanpa membebani Radar default.",
      "Tidak ada perubahan Signal Factory rule, scanner selection, TP/SL formula, threshold, outcome logic, atau execution."
    ],
    impact: "Radar dan Signal History harus lebih jarang blank/504 karena request berat tidak lagi dihitung ulang terus-menerus saat halaman dibuka atau auto-refresh.",
    links: [
      { href: "/scanner", label: "Radar" },
      { href: "/signal-performance", label: "Signal History" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-23",
    title: "V3 Shadow Quality Audit",
    status: "LIVE",
    area: "Signal research",
    summary: "Menambahkan panel audit ke V3 Forward Log untuk membedakan monitoring biasa dengan keputusan riset lane/filter yang layak dipantau.",
    changes: [
      "Endpoint V3 Forward Log sekarang mengirim audit read-only berisi executive verdict, readiness, temuan utama, risk flags, stage decision, dan filter decision.",
      "Halaman V3 Forward Log menampilkan V3/V4 decision audit agar terlihat lane mana yang layak dipantau, mana yang lemah, dan alasannya.",
      "Decision memakai label riset seperti CALIBRATION_CANDIDATE, MONITOR_MORE, DO_NOT_PROMOTE, dan WAIT_SAMPLE; tidak ada live signal atau execution.",
      "Audit ikut membandingkan ideal R, realistic R, drawdown delta, dan konsentrasi symbol supaya filter yang terlihat bagus tidak langsung dipercaya mentah.",
      "Tidak ada perubahan Signal Factory rule, scanner behavior, TP/SL formula, threshold, outcome logic, atau execution."
    ],
    impact: "Kita bisa membaca apakah V3 shadow hanya terlihat bagus karena sample kecil/konsentrasi/biaya realistis, atau memang layak masuk studi V4 berikutnya.",
    links: [
      { href: "/v3-forward-log", label: "V3 Forward Log" },
      { href: "/signal-quality-lab", label: "Signal Quality Lab" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-22",
    title: "Research Loop De-duplication",
    status: "LIVE",
    area: "Ops performance",
    summary: "Menghapus pekerjaan collector yang dobel dari research-loop agar proses VPS fokus ke data processing dan signal logging.",
    changes: [
      "Research-loop tidak lagi menjalankan full collector loop, kline collector, dan snapshot collector inline karena sudah ada PM2 loop khusus.",
      "Menambahkan run_universe_refresh.py untuk refresh active universe secara ringan tanpa ikut mengambil kline/snapshot penuh.",
      "Rich futures collector tetap dipakai untuk evidence, tapi diberi cadence terpisah agar tidak selalu jalan di setiap research cycle.",
      "PM2 ecosystem sekarang mencatat kline-loop, snapshot-loop, dan research-loop; snapshot-loop default diperlambat ke 5 menit.",
      "Tidak ada perubahan Signal Factory rule, scanner behavior, TP/SL formula, threshold, realistic R, atau execution."
    ],
    impact: "CPU/API request berkurang karena proses yang tumpang tindih dimatikan dari research-loop, sementara core candle, snapshot, universe, dan signal tetap berjalan.",
    links: [
      { href: "/data-health", label: "System Health" },
      { href: "/patch-notes", label: "Patch Notes" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-21",
    title: "Collector Snapshot Conflict-Safe Upsert",
    status: "LIVE",
    area: "Collector stability",
    summary: "Memperbaiki duplicate insert pada snapshot time-series seperti current open interest saat Binance mengirim timestamp yang sama lagi.",
    changes: [
      "Current open interest sekarang memakai conflict-safe upsert untuk key symbol + event_time.",
      "Mark/funding current dan futures/spot book ticker ikut memakai helper conflict-safe yang sama karena punya pola unique key sejenis.",
      "Menambahkan test agar dua payload open interest dengan timestamp sama tidak membuat duplicate atau crash.",
      "Tidak ada perubahan Signal Factory rule, scanner behavior, TP/SL, realistic R, atau execution."
    ],
    impact: "Research/collector loop lebih stabil dan tidak membuang waktu karena traceback unique constraint saat data snapshot Binance berulang.",
    links: [
      { href: "/data-health", label: "System Health" },
      { href: "/collectors", label: "Advanced" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-20",
    title: "Lean Core Loop + Legacy Research Pruning",
    status: "LIVE",
    area: "Ops performance + UI cleanup",
    summary: "Core research cycle dipangkas agar proses harian fokus ke Signal Factory, signal logging, dan V3 shadow forward monitor.",
    changes: [
      "Research cycle light tidak lagi menjalankan Strategy Arena, Phase 6 readiness, dan Phase 7 forward test secara otomatis.",
      "Legacy Strategy Arena/Phase 6/Phase 7 masih bisa dijalankan manual dengan env flag MARKETLAB_ENABLE_LEGACY_PHASE7=1 jika diperlukan untuk audit lama.",
      "Overview tidak lagi fetch Phase 6/7 blocker artifact; halaman utama fokus ke Radar, Candidate/Signal, data ready, dan collector pulse.",
      "System Health membaca kematangan 4h/24h dari aggregation health, bukan artifact Phase 7 legacy.",
      "Menu Research/Advanced disederhanakan ke halaman yang masih dipakai: Patch Notes, Signal Quality Lab, V3 Forward Log, Strategy Optimization Lab, Signal Factory Raw, dan Advanced."
    ],
    impact: "Beban otomatis berkurang tanpa mengubah Signal Factory rule, scanner behavior, TP/SL, realistic R, collector, atau execution. Fokus core sekarang lebih ringan untuk observasi dan kalibrasi kualitas signal.",
    links: [
      { href: "/", label: "Overview" },
      { href: "/signal-quality-lab", label: "Signal Quality Lab" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-19",
    title: "Realistic Paper Execution v1",
    status: "LIVE",
    area: "Signal performance realism",
    summary: "Menambahkan perhitungan realistic R read-only untuk membandingkan hasil ideal candle dengan hasil yang terkena fee, spread, dan slippage.",
    changes: [
      "Signal evaluator tetap menghitung Ideal R dari futures candle high/low, lalu menambahkan Realistic R sebagai angka pembanding.",
      "Realistic model memakai asumsi fee per side, slippage per side, dan futures spread dari evidence signal jika tersedia.",
      "BOTH_HIT_SAME_CANDLE sekarang memiliki realistic_result_status konservatif SL_HIT_CONSERVATIVE, tanpa mengubah result ideal.",
      "Signal History menampilkan Ideal R, Realistic R, realism penalty, dan fill quality.",
      "Signal Detail menampilkan realistic entry/exit, cost estimate, spread source, fee/slippage assumption, dan fill quality.",
      "Tidak ada perubahan Signal Factory rule, scanner behavior, threshold, TP/SL reference, atau execution."
    ],
    impact: "Kita bisa melihat seberapa jauh hasil paper ideal dari skenario yang lebih dekat ke live market sebelum optimasi screener dipromosikan.",
    links: [
      { href: "/signal-performance", label: "Signal History" },
      { href: "/scanner", label: "Radar" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-18",
    title: "Signal Forward Integrity Audit",
    status: "LIVE",
    area: "Signal monitoring + UI trust",
    summary: "Menambahkan audit khusus untuk memastikan signal paper-live yang masih open memakai candle futures yang fresh, bukan data symbol yang stale.",
    changes: [
      "Endpoint /api/signals/forward-integrity menampilkan fresh open, stale forward, waiting data, latest global candle, dan gap menit per signal.",
      "Signal History sekarang tetap fokus ke posisi closed, lalu punya panel Forward Integrity untuk open/waiting/stale signal.",
      "Signal Detail menampilkan Forward data, latest symbol candle, global latest candle, dan freshness gap secara eksplisit.",
      "Evaluator menandai STALE_FORWARD_DATA jika candle symbol tertinggal dari global latest futures candle.",
      "Tidak ada perubahan Signal Factory rule, classifier, TP/SL formula, threshold, atau execution."
    ],
    impact: "Jika kasus seperti ASTER terjadi lagi, UI akan menunjukkan data stale atau close TP/SL sesuai candle futures terbaru, bukan membiarkan status Open terlihat valid.",
    links: [
      { href: "/signal-performance", label: "Signal History" },
      { href: "/scanner", label: "Radar" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-17",
    title: "V3 Shadow Forward Log",
    status: "LIVE",
    area: "Research + Forward Monitor",
    summary: "Menambahkan jalur monitoring V3 shadow yang membandingkan hasil forward V2 live dengan subset V3_SHADOW_PASS.",
    changes: [
      "Endpoint /api/v3-shadow/forward-log membaca signal_forward_return_logs dan membentuk lane V3 shadow signal tanpa membuat order.",
      "Script run_v3_shadow_forward_log.py menulis artifact backend/artifacts/v3_shadow_forward/v1/summary.json untuk audit research-loop.",
      "Research cycle sekarang menjalankan V3 shadow forward artifact setelah signal forward return logger.",
      "Halaman /v3-forward-log menampilkan V2 live R, V3 shadow R, retention, open V3, drawdown delta, lane comparison, filter contribution, serta open/closed V3 signals.",
      "V3 tetap shadow/read-only; Signal Factory V2, scanner, TP/SL formula, dan execution tidak berubah."
    ],
    impact: "Kita bisa memantau apakah subset V3 benar-benar lebih stabil dari V2 secara forward, sebelum ada keputusan promosi rule.",
    links: [
      { href: "/v3-forward-log", label: "V3 Forward Log" },
      { href: "/v3-shadow-lab", label: "V3 Shadow Lab" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-16",
    title: "V3 Shadow Comparison Lab",
    status: "LIVE",
    area: "Research + UI",
    summary: "Menambahkan halaman V3 Shadow Lab untuk membandingkan semua Signal V2 dengan subset yang lolos V3 shadow filter.",
    changes: [
      "Menambahkan endpoint /api/v3-shadow/comparison untuk melihat V2 baseline vs V3_SHADOW_PASS.",
      "Halaman /v3-shadow-lab menampilkan V2 evaluated, V2 total R, V3 pass count, V3 total R, avg R delta, dan verdict research-only.",
      "Comparison dipecah berdasarkan V3 status, lane stage/timeframe, dan filter V3 yang berkontribusi.",
      "Tabel contoh latest pass/fail signal membantu audit signal mana yang lolos filter V3 tanpa mengubah rule live.",
      "Radar dan Signal Detail tetap memakai field V3 shadow yang sudah ada; patch ini hanya menambah comparison lab."
    ],
    impact: "Kita bisa memutuskan apakah V3 filter benar-benar memperbaiki kualitas Signal sebelum dipromosikan, tanpa mengubah Signal Factory V2 atau execution.",
    links: [
      { href: "/v3-shadow-lab", label: "V3 Shadow Lab" },
      { href: "/strategy-optimization-lab", label: "Strategy Optimization Lab" }
    ]
  },
  {
    date: "2026-07-10",
    version: "LAB-15",
    title: "Strategy optimization artifacts + V3 shadow snapshot",
    status: "LIVE",
    area: "Research + Ops UI",
    summary: "Strategy Optimization Lab sekarang bisa membaca hasil precomputed artifact dan menampilkan snapshot V3 shadow filter read-only.",
    changes: [
      "Menambahkan runner backend/scripts/run_strategy_optimization_artifacts.py untuk menyimpan optimization/regime split ke backend/artifacts/strategy_optimization/v1/summary.json.",
      "Endpoint /api/strategy-optimization-lab dan /api/strategy-optimization-regime-split sekarang membaca artifact dulu jika filter cocok, lalu fallback ke live compute jika artifact belum ada.",
      "Menambahkan endpoint /api/strategy-optimization-artifacts untuk melihat artifact time, precomputed lane, dan V3 shadow calibration snapshot.",
      "Strategy Optimization Lab menampilkan V3 shadow candidate/monitor/reject count dan top calibration filters tanpa mengubah Signal Factory V2.",
      "Research cycle full ikut menjalankan strategy optimization artifact setelah signal forward return logger."
    ],
    impact: "Halaman optimization lebih cepat dibuka dan kita punya tempat pantau filter V3 shadow secara jelas sebelum ada perubahan rule produksi.",
    links: [
      { href: "/strategy-optimization-lab", label: "Strategy Optimization Lab" },
      { href: "/patch-notes", label: "Patch Notes" }
    ]
  },
  {
    date: "2026-07-09",
    version: "LAB-14",
    title: "Strategy regime split",
    status: "LIVE",
    area: "Research + UI",
    summary: "Strategy Optimization Lab sekarang memecah hasil RR/ATR/timeout berdasarkan BTC, ETH, breadth, dan volatility regime.",
    changes: [
      "Menambahkan endpoint /api/strategy-optimization-regime-split untuk melihat apakah setup seperti MID_SHORT 1h bergantung pada market bearish/risk-off.",
      "Regime split memakai BTCUSDT/ETHUSDT closed futures 1h/4h, breadth active universe, dan average absolute return sebagai volatility proxy.",
      "Halaman Strategy Optimization Lab menampilkan top helpful/harmful regime bucket untuk parameter yang sedang diuji.",
      "Tidak ada perubahan Signal Factory rule, scanner behavior, V3 shadow rule, TP/SL live, threshold live, atau execution."
    ],
    impact: "Kita bisa menjawab apakah MID_SHORT/MID_LONG benar-benar kuat atau hanya terbantu kondisi market tertentu sebelum rule dipromosikan.",
    links: [
      { href: "/strategy-optimization-lab", label: "Strategy Optimization Lab" },
      { href: "/patch-notes", label: "Patch Notes" }
    ]
  },
  {
    date: "2026-07-09",
    version: "LAB-13",
    title: "Strategy Optimization Lab v1",
    status: "LIVE",
    area: "Research + UI",
    summary: "Menambahkan lab read-only untuk menguji kombinasi ATR multiplier, RR, dan timeout dari Signal V2 log.",
    changes: [
      "Menambahkan endpoint /api/strategy-optimization-lab untuk grid RR/ATR/timeout berbasis futures signal log.",
        "ATR memakai ATR14 dari futures 1h yang sudah closed sebelum signal; outcome memakai futures 15m setelah signal.",
        "Menambahkan halaman Strategy Optimization Lab dengan best model per lane dan top parameter grid.",
        "Default Strategy Optimization Lab difokuskan ke MID_SHORT 1h agar halaman live tidak menghitung semua lane berat saat pertama dibuka.",
        "Signal Quality Lab dirapikan dengan panel collapsible agar filter/calibration/regime dan sample signal tidak memenuhi halaman utama.",
        "Tidak ada perubahan Signal Factory rule, scanner behavior, V3 shadow rule, TP/SL live, threshold live, atau execution."
      ],
    impact: "Kita bisa mulai menjawab apakah masalah hasil signal berasal dari SL terlalu dekat, TP terlalu jauh, atau timeout yang belum pas, tanpa mengubah sistem live.",
    links: [
      { href: "/strategy-optimization-lab", label: "Strategy Optimization Lab" },
      { href: "/signal-quality-lab", label: "Signal Quality Lab" }
    ]
  },
  {
    date: "2026-07-09",
    version: "LAB-12",
    title: "Top volume rank return analysis",
    status: "LIVE",
    area: "Research",
    summary: "Signal Quality Lab sekarang membandingkan return R Signal berdasarkan rank volume futures Top 5, Top 10, Top 20, dan All.",
    changes: [
      "Menambahkan agregasi read-only by_volume_rank di endpoint Signal Quality Lab.",
      "Bucket Top 5/10/20 memakai universe_rank dari active universe terbaru, yang berasal dari ranking volume futures.",
      "Tabel baru menampilkan sample, TP/SL/open, winrate, total R, median R, MFE/MAE, top symbol, dan missing rank.",
      "Tidak ada perubahan Signal Factory rule, V3 shadow rule, scanner selection, TP/SL formula, threshold live, outcome logic, atau execution."
    ],
    impact: "Kita bisa cek apakah signal lebih sehat di token volume besar atau justru lebih noisy, tanpa mengubah rule produksi.",
    links: [
      { href: "/signal-quality-lab", label: "Signal Quality Lab" },
      { href: "/patch-notes", label: "Patch Notes" }
    ]
  },
  {
    date: "2026-07-09",
    version: "LAB-11",
    title: "Signal Factory V3 shadow evaluation",
    status: "LIVE",
    area: "Research + UI",
    summary: "Radar, Signal History, dan Signal Detail sekarang menampilkan versi strategy live V2 serta status V3 shadow calibration.",
    changes: [
      "Menambahkan evaluasi V3 shadow read-only dari filter Calibration Lab yang berstatus V3_CANDIDATE.",
      "Radar menampilkan Strategy dan V3 shadow status per signal supaya jelas signal berasal dari V2 live dan apakah lolos filter V3 candidate.",
      "Signal History closed-only menampilkan versi strategy dan status V3 shadow untuk audit TP/SL hasil lama.",
      "Signal Detail menampilkan kartu Live strategy, Shadow strategy, V3 shadow status, dan V3 filter score.",
      "Tidak ada perubahan Signal Factory rule, scanner selection, TP/SL formula, threshold live, outcome logic, atau execution."
    ],
    impact: "Kita bisa membandingkan V2 live vs V3 shadow tanpa mengganti rule produksi. Ini tahap observasi sebelum filter V3 boleh dipromosikan.",
    links: [
      { href: "/scanner", label: "Radar" },
      { href: "/signal-performance", label: "Signal History" },
      { href: "/signal-quality-lab", label: "Signal Quality Lab" }
    ]
  },
  {
    date: "2026-07-09",
    version: "LAB-10",
    title: "Calibration promotion readiness",
    status: "LIVE",
    area: "Research",
    summary: "Signal Quality Lab sekarang membedakan filter V3 candidate, monitor more, reject overfit, dan weak filter.",
    changes: [
      "Menambahkan promotion readiness read-only di endpoint calibration-lab.",
      "Filter baru disebut V3 candidate hanya jika train dan validation cukup, validation membaik, total R positif, SL share tidak memburuk, dan symbol concentration masih wajar.",
      "Kartu prioritas Early Long 15m dan Mid Short 1h sekarang menampilkan promotion score serta alasan kenapa filter dipantau atau ditolak.",
      "Tidak ada perubahan Signal Factory rule, scanner behavior, TP/SL formula, outcome logic, atau execution."
    ],
    impact: "Riset filter jadi lebih disiplin: kita bisa lihat mana yang cukup layak dipantau untuk V3 dan mana yang hanya terlihat bagus karena overfit.",
    links: [
      { href: "/signal-quality-lab", label: "Signal Quality Lab" },
      { href: "/patch-notes", label: "Patch Notes" }
    ]
  },
  {
    date: "2026-07-09",
    version: "LAB-09",
    title: "Priority signal calibration focus",
    status: "LIVE",
    area: "Research",
    summary: "Signal Quality Lab sekarang menyorot dua lane prioritas: Early Long 15m dan Mid Short 1h.",
    changes: [
      "Menambahkan kartu prioritas untuk Early Long 15m sebagai fokus momentum fresh long.",
      "Menambahkan kartu prioritas untuk Mid Short 1h sebagai fokus short context yang masih layak dipantau.",
      "Setiap kartu menampilkan sample, train/validation, baseline total R, validation average R, filter terbaik sementara, dan warning agar belum dipromosikan ke rule produksi.",
      "Tidak ada perubahan Signal Factory rule, scanner behavior, TP/SL formula, outcome logic, atau execution."
    ],
    impact: "Riset berikutnya lebih terarah: fokus dulu ke dua setup yang datanya paling masuk akal, bukan menyebar ke semua lane sekaligus.",
    links: [
      { href: "/signal-quality-lab", label: "Signal Quality Lab" },
      { href: "/signal-performance", label: "Signal History" }
    ]
  },
  {
    date: "2026-07-09",
    version: "LAB-08",
    title: "Signal Calibration Lab v1",
    status: "LIVE",
    area: "Research",
    summary: "Signal Quality Lab sekarang punya calibration view train/validation untuk mencari filter Early/Mid yang bertahan di validation.",
    changes: [
      "Menambahkan endpoint read-only /api/signal-candidates/calibration-lab.",
      "Calibration Lab membandingkan baseline vs filter dengan split kronologis 70/30 train dan validation.",
      "Halaman Signal Quality Lab menampilkan active lane, ready lane, promising filter, overfit train-only, dan top calibration candidates.",
      "Tidak ada perubahan Signal Factory rule, scanner behavior, TP/SL formula, outcome logic, atau execution."
    ],
    impact: "Kita bisa mulai mencari filter yang benar-benar memperbaiki signal berdasarkan data live, tanpa langsung mempromosikan threshold ke produksi.",
    links: [
      { href: "/signal-quality-lab", label: "Signal Quality Lab" },
      { href: "/signal-performance", label: "Signal History" }
    ]
  },
  {
    date: "2026-07-08",
    version: "UI-12",
    title: "Realtime signal detail refresh",
    status: "LIVE",
    area: "Frontend + Ops",
    summary: "Signal detail dan Radar sekarang refresh otomatis, sementara kline 1m dipisah dari research-loop berat.",
    changes: [
      "Signal detail auto-refresh setiap 30 detik agar current R dan latest eval price ikut bergerak tanpa klik manual.",
      "Radar auto-refresh setiap 30 detik agar snapshot Signal terbaru ikut kebaca.",
      "Kline collector VPS berjalan sebagai PM2 process terpisah sehingga data 1m tidak ikut tertahan Strategy Arena/research-loop berat.",
      "RR/TP/SL reference tetap angka tetap dari signal; yang bergerak adalah current R, latest eval price, MFE/MAE, dan status TP/SL."
    ],
    impact: "Halaman detail tidak lagi diam di candle lama selama kline 1m terus masuk. Tidak ada perubahan Signal Factory rule, scoring, TP/SL, atau execution.",
    links: [
      { href: "/scanner", label: "Radar" },
      { href: "/signals/LINKUSDT", label: "Signal Detail" }
    ]
  },
  {
    date: "2026-07-08",
    version: "UI-11",
    title: "Signal detail page and closed-only history",
    status: "LIVE",
    area: "Frontend + API",
    summary: "Radar sekarang membuka halaman detail signal penuh, sementara Signal History fokus ke signal yang sudah close.",
    changes: [
      "Tombol Detail di Radar mengarah ke halaman detail signal, bukan expand inline di tabel.",
      "Halaman detail signal menampilkan status posisi, current/final R, entry futures, SL, TP, MFE/MAE, dan evidence lengkap.",
      "Signal History default membaca closed-only TP/SL/BOTH agar tidak tercampur posisi open.",
      "Tidak ada perubahan Signal Factory rule, scoring, TP/SL formula, atau execution."
    ],
    impact: "Radar dipakai untuk membaca signal aktif sekarang; Signal History dipakai untuk audit hasil yang sudah close.",
    links: [
      { href: "/scanner", label: "Radar" },
      { href: "/signal-performance", label: "Signal History" }
    ]
  },
  {
    date: "2026-07-08",
    version: "UI-10",
    title: "Signal naming cleanup",
    status: "LIVE",
    area: "Frontend",
    summary: "Output final read-only di UI sekarang disebut Signal, bukan calon signal.",
    changes: [
      "Radar tetap berarti aktivitas awal.",
      "Candidate tetap berarti konteks yang layak dipantau tetapi belum final.",
      "Signal berarti output final read-only dengan entry futures reference, SL, TP, RR, dan alasan numerik.",
      "Backend enum/API tetap memakai SIGNAL_CANDIDATE untuk kompatibilitas data; tidak ada rule, threshold, TP/SL, atau execution yang berubah."
    ],
    impact: "Hierarchy UI lebih jelas: Radar -> Candidate -> Signal, tanpa mengubah cara sistem mengambil keputusan.",
    links: [
      { href: "/scanner?tier=SIGNAL_CANDIDATE&limit=75", label: "Signal" },
      { href: "/signal-performance", label: "Signal History" }
    ]
  },
  {
    date: "2026-07-08",
    version: "PERF-04",
    title: "Signal TP/SL matching uses closed 1m futures candles",
    status: "LIVE",
    area: "Signal History",
    summary: "Signal History sekarang mengecek TP/SL dari futures 1m closed candle, bukan menunggu agregasi 15m.",
    changes: [
      "Evaluator paper-live Signal membaca futures_klines_1m untuk hit TP/SL.",
      "Latest eval candle di halaman Signal History menampilkan candle evaluasi 1m terbaru.",
      "Quality Lab dan Filter Study ikut memakai evaluasi 1m yang sama.",
      "Tidak ada perubahan Signal Factory rule, threshold, entry reference, TP/SL reference, atau execution."
    ],
    impact: "Status open/TP/SL lebih cepat mengikuti harga setelah candle 1m tersedia, sehingga kasus harga sudah jauh lewat TP tidak menunggu candle 15m selesai.",
    links: [
      { href: "/signal-performance", label: "Signal History" },
      { href: "/signal-quality-lab", label: "Signal Quality Lab" }
    ]
  },
  {
    date: "2026-07-08",
    version: "UI-09",
    title: "Price precision for small-token signal references",
    status: "LIVE",
    area: "Frontend",
    summary: "Entry, SL, dan TP untuk token harga kecil sekarang ditampilkan dengan digit cukup agar tidak terlihat sama.",
    changes: [
      "Menambahkan formatter harga khusus untuk price/entry/SL/TP.",
      "Signal History memakai formatter harga baru untuk kolom Entry, SL, dan TP.",
      "Radar memakai formatter harga baru untuk futures reference, SL, dan TP.",
      "Tidak ada perubahan perhitungan Signal Factory, TP/SL, outcome, atau execution."
    ],
    impact: "Token seperti 1000SHIBUSDT tidak lagi terlihat entry dan SL sama hanya karena pembulatan tampilan.",
    links: [
      { href: "/signal-performance", label: "Signal History" },
      { href: "/scanner", label: "Radar" }
    ]
  },
  {
    date: "2026-07-07",
    version: "LAB-07",
    title: "Signal Quality Lab filter and regime studies",
    status: "LIVE",
    area: "Research",
    summary: "Halaman Quality Lab sekarang memuat Filter Study dan Market Regime Study untuk membedah Signal dari data live.",
    changes: [
      "Filter Study 1h MID_SHORT/MID_LONG ditampilkan di Signal Quality Lab untuk melihat filter mana yang memperbaiki atau merusak hasil.",
      "Optuna filter discovery dibuat read-only untuk MID_SHORT/MID_LONG 1h; hasil validation belum layak dipromosikan menjadi rule.",
      "Market Regime Study v1 ditambahkan: split hasil berdasarkan BTC, ETH, breadth market, dan volatility.",
      "Patch ini tidak mengubah Signal Factory rule, scanner behavior, outcome logic, TP/SL, atau execution."
    ],
    impact: "Riset kualitas signal sekarang bisa dilihat dari web: filter apa yang membantu, dan kondisi market apa yang membuat setup menjadi bagus atau buruk.",
    links: [
      { href: "/signal-quality-lab", label: "Signal Quality Lab" },
      { href: "/signal-factory", label: "Signal Factory Raw" }
    ]
  },
  {
    date: "2026-07-07",
    version: "LAB-04",
    title: "Evidence TP vs SL analysis",
    status: "LIVE",
    area: "Research",
    summary: "Signal Quality Lab sekarang membandingkan angka evidence aktual antara signal yang TP dan SL.",
    changes: [
      "Menambahkan tabel Evidence TP vs SL.",
      "Menampilkan median, kuartil, delta TP-SL, available count, dan missing count per field.",
      "Field yang dibandingkan mencakup price return, volume ratio, taker ratio, OI, funding, spread, rich ratio, core score, dan evidence score.",
      "Tabel mengikuti filter stage, timeframe, position lock, WATCH_ONLY, dan min sample."
    ],
    impact: "Kalibrasi Early/Mid bisa mulai dilakukan dari angka aktual signal yang menang/kalah, bukan tebakan threshold.",
    links: [
      { href: "/signal-quality-lab", label: "Signal Quality Lab" }
    ]
  },
  {
    date: "2026-07-06",
    version: "UI-08",
    title: "Full-width dashboard layout",
    status: "LIVE",
    area: "Frontend",
    summary: "Layout web dibuat full-width supaya tabel lebih banyak muat di layar desktop.",
    changes: [
      "Container utama tidak lagi dikunci max-width kecil.",
      "Padding kanan-kiri halaman dan navbar diperkecil.",
      "Tabel global dibuat lebih kompak.",
      "Lebar minimum tabel besar dikurangi supaya horizontal scroll lebih jarang muncul."
    ],
    impact: "Halaman seperti Signal Quality Lab, Radar, Strategy Test, dan System Health memakai ruang layar lebih maksimal.",
    links: [
      { href: "/signal-quality-lab", label: "Signal Quality Lab" },
      { href: "/scanner", label: "Radar" }
    ]
  },
  {
    date: "2026-07-06",
    version: "LAB-03",
    title: "Signal Quality Lab",
    status: "LIVE",
    area: "Research",
    summary: "Halaman analisis kualitas signal ditambahkan untuk membedah kenapa Signal menang atau kalah.",
    changes: [
      "Menambahkan breakdown TP/SL/R berdasarkan stage, confidence, timeframe, dan symbol.",
      "Menambahkan best signal, worst signal, open signal, dan drawdown R sederhana.",
      "Menambahkan filter stage, timeframe, min sample, position lock, dan WATCH_ONLY.",
      "Semua analisis tetap read-only dan tidak mengubah rule Signal Factory."
    ],
    impact: "MarketLab sekarang punya tempat khusus untuk kalibrasi kualitas signal dari data live yang sudah terkumpul.",
    links: [
      { href: "/signal-quality-lab", label: "Signal Quality Lab" },
      { href: "/signal-performance", label: "Signal History" }
    ]
  },
  {
    date: "2026-07-06",
    version: "UI-07",
    title: "Navigation cleanup and Phase 7 page removal",
    status: "LIVE",
    area: "Frontend",
    summary: "Navbar dirapikan agar halaman harian tidak bercampur dengan halaman riset/debug.",
    changes: [
      "Menu utama dipersempit menjadi Overview, Radar, Signal History, System Health, dan Universe.",
      "Early Lab, Strategy Test, Signal Gate Audit, Signal Factory Raw, dan Advanced dipindah ke Research / Advanced.",
      "Halaman Phase 7 dihapus dari web. Backend artifact lama tetap ada untuk audit internal.",
      "Istilah user-facing diganti dari Phase 7 menjadi Signal Gate atau Forward Test agar lebih jelas."
    ],
    impact: "Web lebih mudah dibaca: halaman harian fokus ke monitoring, halaman riset/debug masuk dropdown.",
    links: [
      { href: "/", label: "Overview" },
      { href: "/phase6-audit", label: "Signal Gate Audit" }
    ]
  },
  {
    date: "2026-07-06",
    version: "UI-06",
    title: "Radar separated from Signal History",
    status: "LIVE",
    area: "Frontend",
    summary: "Radar dan Signal History dipisahkan supaya tidak punya fungsi yang tumpang tindih.",
    changes: [
      "Radar sekarang hanya menampilkan snapshot kandidat terbaru per symbol.",
      "Blok performance dan history dihapus dari Radar.",
      "Signal History menjadi tempat khusus untuk arsip hasil TP/SL paper-live.",
      "Copy halaman diperjelas: Radar bukan performance, Signal History bukan daftar kandidat terbaru."
    ],
    impact: "Alur baca menjadi jelas: Radar untuk kondisi sekarang, Signal History untuk hasil signal yang sudah lewat.",
    links: [
      { href: "/scanner", label: "Radar" },
      { href: "/signal-performance", label: "Signal History" }
    ]
  },
  {
    date: "2026-07-06",
    version: "PERF-03",
    title: "Signal History loading fix",
    status: "LIVE",
    area: "Backend + Frontend",
    summary: "Signal History sempat terlihat kosong karena endpoint performance terlalu lambat dan kena timeout.",
    changes: [
      "Query candle performance dibuat lebih ringan.",
      "Endpoint signal performance diberi cache pendek 30 detik.",
      "Default row history dikurangi dari 100 ke 50 agar load awal lebih cepat.",
      "Proxy frontend ke backend diperbaiki agar /api browser tidak 404."
    ],
    impact: "Signal History sekarang menampilkan data TP/SL paper-live tanpa stuck loading lama.",
    links: [
      { href: "/signal-performance", label: "Signal History" }
    ]
  },
  {
    date: "2026-07-06",
    version: "SCAN-04",
    title: "Scanner focused on Signal",
    status: "LIVE",
    area: "Scanner",
    summary: "Scanner difokuskan ke Signal sebagai output final read-only.",
    changes: [
      "Default Radar filter diarahkan ke SIGNAL_CANDIDATE.",
      "Signal non-15m ikut tampil jika Signal Factory menghasilkan timeframe itu.",
      "Payload scanner menampilkan timeframe, entry futures reference, SL, TP, RR, timeout, dan alasan.",
      "Inactive/blocked/baseline tetap bisa diaudit lewat filter, tapi tidak mendominasi default page."
    ],
    impact: "User bisa langsung cek kandidat final tanpa terganggu Radar/Context yang belum final.",
    links: [
      { href: "/scanner?tier=SIGNAL_CANDIDATE&limit=75", label: "Signal" },
      { href: "/signal-factory", label: "Signal Factory Raw" }
    ]
  },
  {
    date: "2026-07-06",
    version: "OPS-05",
    title: "Research loop and lock stability",
    status: "LIVE",
    area: "Pipeline",
    summary: "Loop riset dan collector dibuat lebih tahan terhadap stale lock dan cycle berat.",
    changes: [
      "Run lock JSON dengan stale recovery ditambahkan ke beberapa runner.",
      "Research cycle bug step selection diperbaiki.",
      "Scanner loop dipisah dari maintenance berat agar halaman live tidak terlalu tertinggal.",
      "Aggregation dan downstream builder dibatasi ke window terbaru supaya cycle tidak makin lambat."
    ],
    impact: "Pipeline lebih stabil, lebih kecil kemungkinan skip berulang karena lock lama.",
    links: [
      { href: "/data-health", label: "System Health" },
      { href: "/collectors", label: "Advanced" }
    ]
  },
  {
    date: "2026-07-06",
    version: "LAB-02",
    title: "Early Lab and paper-style signal testing",
    status: "LIVE",
    area: "Research",
    summary: "Early Lab dibuat untuk menguji definisi Early Long dan Early Short dari data historis.",
    changes: [
      "Early Lab menampilkan multi-horizon result 15m, 1h, 4h, dan 24h jika data tersedia.",
      "Entry, SL, TP, RR, realized R, dan token history dibuat lebih eksplisit.",
      "Position lock digunakan agar satu symbol tidak membuka banyak posisi paper bersamaan.",
      "Result dipisah dari live Signal agar lab tidak tercampur dengan monitoring harian."
    ],
    impact: "Definisi early bisa diuji sebagai riset tanpa mengubah rule live scanner.",
    links: [
      { href: "/early-backtest-lab", label: "Early Lab" }
    ]
  },
  {
    date: "2026-07-05",
    version: "DATA-08",
    title: "Evidence and risk data remediation",
    status: "LIVE",
    area: "Data Pipeline",
    summary: "Evidence V2 sempat kosong karena bug mapping timestamp, bukan karena Binance API kosong.",
    changes: [
      "Root cause evidence/risk missing diperiksa per field.",
      "Spread, OI, funding, rich alignment, long/short ratio, dan top trader evidence mulai masuk ke output.",
      "Evidence completeness dipakai untuk membedakan netral genuine vs data tidak tersedia.",
      "Forward-return logging mulai berjalan sebagai data observasi resmi."
    ],
    impact: "Confidence dan risk gate mulai punya data nyata, bukan angka dari field kosong.",
    links: [
      { href: "/signal-factory", label: "Signal Factory Raw" },
      { href: "/signal-performance", label: "Signal History" }
    ]
  },
  {
    date: "2026-07-04",
    version: "CORE-01",
    title: "Multi-timeframe Signal Factory and Strategy Arena",
    status: "LIVE",
    area: "Research Core",
    summary: "MarketLab mulai punya jalur research dari feature, signal factory, strategy test, sampai gate audit.",
    changes: [
      "Signal Factory V2 menghasilkan Radar, Candidate, dan Signal read-only.",
      "Strategy Arena menguji setup dengan ATR/RR dan horizon berbeda.",
      "Signal Gate Audit membandingkan readiness, edge, score, ATR, dan blocker.",
      "Semua tetap read-only: tidak ada execution, order, final TP/SL live, atau position sizing."
    ],
    impact: "MarketLab punya alur riset terukur sebelum masuk keputusan live apa pun.",
    links: [
      { href: "/strategy-arena", label: "Strategy Test" },
      { href: "/phase6-audit", label: "Signal Gate Audit" }
    ]
  }
];

export default function PatchNotesPage() {
  const latest = patches[0];
  return (
    <div className="space-y-5">
      <PageHeader
        title="Patch Notes"
        badge="CHANGELOG - PRODUCT HISTORY"
        subtitle="Riwayat perubahan MarketLab yang sudah ditambahkan ke web dan pipeline. Ini bukan log git mentah, tapi ringkasan perubahan yang relevan untuk pemakaian."
        updatedAt={latest.date}
      />

      <section className="grid gap-3 md:grid-cols-3">
        <div className="rounded border border-line bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Latest patch</div>
          <div className="mt-2 text-lg font-bold text-ink">{latest.version}</div>
          <div className="mt-1 text-sm text-slate-600">{latest.title}</div>
        </div>
        <div className="rounded border border-line bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Live patches</div>
          <div className="mt-2 text-lg font-bold text-ink">{patches.filter((patch) => patch.status === "LIVE").length}</div>
          <div className="mt-1 text-sm text-slate-600">Semua item di halaman ini sudah live atau tersedia di repo.</div>
        </div>
        <div className="rounded border border-line bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Main focus</div>
          <div className="mt-2 text-lg font-bold text-ink">Monitoring + Quality</div>
          <div className="mt-1 text-sm text-slate-600">Radar, Signal History, System Health, dan riset quality signal.</div>
        </div>
      </section>

      <SectionCard title="Patch timeline" description="Urutan perubahan produk dari yang terbaru ke yang lebih lama.">
        <div className="divide-y divide-line">
          {patches.map((patch) => (
            <article className="grid gap-4 p-4 lg:grid-cols-[11rem_1fr]" key={`${patch.version}-${patch.title}`}>
              <div>
                <div className="text-sm font-semibold text-slate-600">{patch.date}</div>
                <div className="mt-2"><StatusBadge value={patch.status} /></div>
                <div className="mt-2 text-xs font-semibold uppercase text-slate-500">{patch.version}</div>
                <div className="mt-1 text-xs text-slate-500">{patch.area}</div>
              </div>
              <div className="space-y-3">
                <div>
                  <h2 className="text-lg font-bold text-ink">{patch.title}</h2>
                  <p className="mt-1 text-sm leading-6 text-slate-600">{patch.summary}</p>
                </div>
                <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
                  <ul className="list-disc space-y-1 pl-5 text-sm leading-6 text-slate-700">
                    {patch.changes.map((change) => (
                      <li key={change}>{change}</li>
                    ))}
                  </ul>
                  <div className="rounded border border-line bg-field/50 p-3 text-sm">
                    <div className="font-semibold text-ink">Impact</div>
                    <p className="mt-1 leading-6 text-slate-600">{patch.impact}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {patch.links.map((link) => (
                        <Link className="rounded border border-line bg-white px-2 py-1 text-xs font-semibold hover:bg-field" href={link.href} key={link.href}>
                          {link.label}
                        </Link>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
