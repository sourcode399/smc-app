"""
smc/catalog.py — DANH MỤC MÃ CHỌN SẴN
======================================
Tách riêng để bạn dễ tự thêm/bớt mã. Mỗi mục:  "Tên hiển thị": (market, symbol)

    market: 'crypto'    -> ccxt   (định dạng BTC/USDT)
            'commodity' -> Yahoo  (hàng hoá, mã =F)
            'forex'     -> Yahoo  (mã =X)
            'index'     -> Yahoo  (mã ^...)
            'stock'     -> Yahoo  (cổ phiếu Mỹ)
            'vn'        -> vnstock (chứng khoán VN, mã 3 ký tự / VNINDEX / VN30)

Muốn thêm mã: chỉ cần chèn 1 dòng vào đúng nhóm. Mã sai sẽ báo lỗi khi chọn,
không làm hỏng app — cứ thử thoải mái.
"""

CATALOG = {
    # ---------------------------------------------------------------- CRYPTO
    "Crypto": {
        "Bitcoin (BTC)":   ("crypto", "BTC/USDT"),
        "Ethereum (ETH)":  ("crypto", "ETH/USDT"),
        "BNB":             ("crypto", "BNB/USDT"),
        "Solana (SOL)":    ("crypto", "SOL/USDT"),
        "XRP":             ("crypto", "XRP/USDT"),
        "Cardano (ADA)":   ("crypto", "ADA/USDT"),
        "Dogecoin (DOGE)": ("crypto", "DOGE/USDT"),
        "Avalanche (AVAX)":("crypto", "AVAX/USDT"),
        "Polkadot (DOT)":  ("crypto", "DOT/USDT"),
        "Chainlink (LINK)":("crypto", "LINK/USDT"),
        "Litecoin (LTC)":  ("crypto", "LTC/USDT"),
        "TRON (TRX)":      ("crypto", "TRX/USDT"),
        "Polygon (POL)":   ("crypto", "POL/USDT"),
        "Toncoin (TON)":   ("crypto", "TON/USDT"),
        "Cosmos (ATOM)":   ("crypto", "ATOM/USDT"),
        "NEAR":            ("crypto", "NEAR/USDT"),
        "Aptos (APT)":     ("crypto", "APT/USDT"),
        "Sui (SUI)":       ("crypto", "SUI/USDT"),
        "Arbitrum (ARB)":  ("crypto", "ARB/USDT"),
        "Optimism (OP)":   ("crypto", "OP/USDT"),
        "Uniswap (UNI)":   ("crypto", "UNI/USDT"),
        "Injective (INJ)": ("crypto", "INJ/USDT"),
        "Pepe (PEPE)":     ("crypto", "PEPE/USDT"),
        "Shiba Inu (SHIB)":("crypto", "SHIB/USDT"),
    },

    # -------------------------------------------------------------- HÀNG HOÁ
    "Hàng hoá": {
        "Vàng (GC=F)":         ("commodity", "GC=F"),
        "Bạc (SI=F)":          ("commodity", "SI=F"),
        "Bạch kim (PL=F)":     ("commodity", "PL=F"),
        "Palladium (PA=F)":    ("commodity", "PA=F"),
        "Đồng (HG=F)":         ("commodity", "HG=F"),
        "Dầu WTI (CL=F)":      ("commodity", "CL=F"),
        "Dầu Brent (BZ=F)":    ("commodity", "BZ=F"),
        "Khí gas (NG=F)":      ("commodity", "NG=F"),
        "Xăng (RB=F)":         ("commodity", "RB=F"),
        "Ngô (ZC=F)":          ("commodity", "ZC=F"),
        "Lúa mì (ZW=F)":       ("commodity", "ZW=F"),
        "Đậu tương (ZS=F)":    ("commodity", "ZS=F"),
        "Cà phê (KC=F)":       ("commodity", "KC=F"),
        "Đường (SB=F)":        ("commodity", "SB=F"),
        "Cacao (CC=F)":        ("commodity", "CC=F"),
        "Bông (CT=F)":         ("commodity", "CT=F"),
    },

    # ----------------------------------------------------------------- FOREX
    "Forex": {
        "EUR/USD": ("forex", "EURUSD=X"),
        "GBP/USD": ("forex", "GBPUSD=X"),
        "USD/JPY": ("forex", "USDJPY=X"),
        "USD/CHF": ("forex", "USDCHF=X"),
        "AUD/USD": ("forex", "AUDUSD=X"),
        "NZD/USD": ("forex", "NZDUSD=X"),
        "USD/CAD": ("forex", "USDCAD=X"),
        "EUR/JPY": ("forex", "EURJPY=X"),
        "GBP/JPY": ("forex", "GBPJPY=X"),
        "EUR/GBP": ("forex", "EURGBP=X"),
        "USD/CNY": ("forex", "USDCNY=X"),
        "Chỉ số USD (DXY)": ("commodity", "DX=F"),
    },

    # ----------------------------------------------------------------- CHỈ SỐ
    "Chỉ số": {
        "S&P 500 (^GSPC)":   ("index", "^GSPC"),
        "Nasdaq (^IXIC)":    ("index", "^IXIC"),
        "Dow Jones (^DJI)":  ("index", "^DJI"),
        "Russell 2000 (^RUT)": ("index", "^RUT"),
        "VIX (^VIX)":        ("index", "^VIX"),
        "Nikkei 225 (^N225)":("index", "^N225"),
        "Hang Seng (^HSI)":  ("index", "^HSI"),
        "FTSE 100 (^FTSE)":  ("index", "^FTSE"),
        "DAX (^GDAXI)":      ("index", "^GDAXI"),
        "CAC 40 (^FCHI)":    ("index", "^FCHI"),
        "KOSPI (^KS11)":     ("index", "^KS11"),
    },

    # ------------------------------------------------------- CHỨNG KHOÁN VN
    "Chứng khoán VN": {
        "VN-Index":          ("vn", "VNINDEX"),
        "VN30":              ("vn", "VN30"),
        # Ngân hàng
        "Vietcombank (VCB)": ("vn", "VCB"),
        "BIDV (BID)":        ("vn", "BID"),
        "VietinBank (CTG)":  ("vn", "CTG"),
        "Techcombank (TCB)": ("vn", "TCB"),
        "MB Bank (MBB)":     ("vn", "MBB"),
        "ACB":               ("vn", "ACB"),
        "VPBank (VPB)":      ("vn", "VPB"),
        "Sacombank (STB)":   ("vn", "STB"),
        "HDBank (HDB)":      ("vn", "HDB"),
        "TPBank (TPB)":      ("vn", "TPB"),
        "SHB":               ("vn", "SHB"),
        # Bất động sản
        "Vingroup (VIC)":    ("vn", "VIC"),
        "Vinhomes (VHM)":    ("vn", "VHM"),
        "Vincom Retail (VRE)": ("vn", "VRE"),
        "Novaland (NVL)":    ("vn", "NVL"),
        "Phát Đạt (PDR)":    ("vn", "PDR"),
        "DIC Corp (DIG)":    ("vn", "DIG"),
        "Đất Xanh (DXG)":    ("vn", "DXG"),
        "Khang Điền (KDH)":  ("vn", "KDH"),
        # Thép & vật liệu
        "Hoà Phát (HPG)":    ("vn", "HPG"),
        "Hoa Sen (HSG)":     ("vn", "HSG"),
        "Nam Kim (NKG)":     ("vn", "NKG"),
        # Bán lẻ & tiêu dùng
        "Thế Giới Di Động (MWG)": ("vn", "MWG"),
        "Masan (MSN)":       ("vn", "MSN"),
        "Vinamilk (VNM)":    ("vn", "VNM"),
        "Sabeco (SAB)":      ("vn", "SAB"),
        "PNJ":               ("vn", "PNJ"),
        "FPT Retail (FRT)":  ("vn", "FRT"),
        # Năng lượng & dầu khí
        "PV Gas (GAS)":      ("vn", "GAS"),
        "Petrolimex (PLX)":  ("vn", "PLX"),
        "PV Power (POW)":    ("vn", "POW"),
        "PVDrilling (PVD)":  ("vn", "PVD"),
        "PVS":               ("vn", "PVS"),
        # Chứng khoán
        "SSI":               ("vn", "SSI"),
        "VNDirect (VND)":    ("vn", "VND"),
        "HCM (HSC)":         ("vn", "HCM"),
        "Vietcap (VCI)":     ("vn", "VCI"),
        # Công nghệ & khác
        "FPT":               ("vn", "FPT"),
        "Vietjet (VJC)":     ("vn", "VJC"),
        "Vietnam Airlines (HVN)": ("vn", "HVN"),
        "GVR (Cao su)":      ("vn", "GVR"),
        "Gemadept (GMD)":    ("vn", "GMD"),
        "REE":               ("vn", "REE"),
    },

    # ------------------------------------------------------- CỔ PHIẾU MỸ
    "Cổ phiếu Mỹ": {
        "Apple (AAPL)":      ("stock", "AAPL"),
        "Microsoft (MSFT)":  ("stock", "MSFT"),
        "Nvidia (NVDA)":     ("stock", "NVDA"),
        "Tesla (TSLA)":      ("stock", "TSLA"),
        "Amazon (AMZN)":     ("stock", "AMZN"),
        "Alphabet (GOOGL)":  ("stock", "GOOGL"),
        "Meta (META)":       ("stock", "META"),
        "Netflix (NFLX)":    ("stock", "NFLX"),
        "AMD":               ("stock", "AMD"),
        "Intel (INTC)":      ("stock", "INTC"),
        "Coinbase (COIN)":   ("stock", "COIN"),
        "Palantir (PLTR)":   ("stock", "PLTR"),
        "Alibaba (BABA)":    ("stock", "BABA"),
        "JPMorgan (JPM)":    ("stock", "JPM"),
        "Visa (V)":          ("stock", "V"),
        "Disney (DIS)":      ("stock", "DIS"),
        "Boeing (BA)":       ("stock", "BA"),
        "Coca-Cola (KO)":    ("stock", "KO"),
        "Walmart (WMT)":     ("stock", "WMT"),
    },
}
