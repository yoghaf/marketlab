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
