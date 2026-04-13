/**
 * APRS Symbol Icon Picker — visual symbol selector for station settings.
 *
 * Standard APRS symbols use a table character ("/" primary or "\" alternate)
 * and a symbol code character (ASCII 33–126). This module provides a friendly
 * visual grid with emoji representations and human-readable names.
 *
 * Official APRS symbol definitions from:
 *   https://www.aprs.org/symbols/symbolsX.txt   (master symbol spec)
 *   https://www.aprs.org/symbols/symbols-new.txt (overlay expansions, APRS 1.2)
 *
 * Overlay / Expansion symbols:
 *   All alternate symbols may carry an overlay character (0-9, A-Z, a-z).
 *   The TABLE byte in the APRS position report carries the overlay character
 *   instead of "\".  APRS_OVERLAYS maps (symbolCode, overlayChar) → name/emoji.
 */

const APRS_SYMBOLS = {
    // ─── Primary Symbol Table "/" ──────────────────────────────────────
    "/": [
        { code: "!", emoji: "👮", name: "Police / Sheriff" },
        { code: '"', emoji: "⬜", name: "Reserved" },
        { code: "#", emoji: "📡", name: "Digipeater" },
        { code: "$", emoji: "📞", name: "Phone" },
        { code: "%", emoji: "📊", name: "DX Cluster" },
        { code: "&", emoji: "🔷", name: "HF Gateway" },
        { code: "'", emoji: "✈️", name: "Small Aircraft" },
        { code: "(", emoji: "📡", name: "Mobile Satellite Stn" },
        { code: ")", emoji: "♿", name: "Wheelchair" },
        { code: "*", emoji: "🏂", name: "Snowmobile" },
        { code: "+", emoji: "➕", name: "Red Cross" },
        { code: ",", emoji: "⚜️", name: "Boy Scouts" },
        { code: "-", emoji: "🏠", name: "House QTH (VHF)" },
        { code: ".", emoji: "❌", name: "X" },
        { code: "/", emoji: "🔴", name: "Red Dot" },
        { code: "0", emoji: "0️⃣", name: "Circle 0" },
        { code: "1", emoji: "1️⃣", name: "Circle 1" },
        { code: "2", emoji: "2️⃣", name: "Circle 2" },
        { code: "3", emoji: "3️⃣", name: "Circle 3" },
        { code: "4", emoji: "4️⃣", name: "Circle 4" },
        { code: "5", emoji: "5️⃣", name: "Circle 5" },
        { code: "6", emoji: "6️⃣", name: "Circle 6" },
        { code: "7", emoji: "7️⃣", name: "Circle 7" },
        { code: "8", emoji: "8️⃣", name: "Circle 8" },
        { code: "9", emoji: "9️⃣", name: "Circle 9" },
        { code: ":", emoji: "🔥", name: "Fire" },
        { code: ";", emoji: "⛺", name: "Campground / Portable" },
        { code: "<", emoji: "🏍️", name: "Motorcycle" },
        { code: "=", emoji: "🚂", name: "Railroad Engine" },
        { code: ">", emoji: "🚗", name: "Car" },
        { code: "?", emoji: "🖥️", name: "File Server" },
        { code: "@", emoji: "🌐", name: "HC FUTURE Predict" },
        { code: "A", emoji: "🏥", name: "Aid Station" },
        { code: "B", emoji: "📮", name: "BBS" },
        { code: "C", emoji: "🛶", name: "Canoe" },
        { code: "D", emoji: "⬜", name: "Undefined" },
        { code: "E", emoji: "👁️", name: "Eyeball / Event" },
        { code: "F", emoji: "🚜", name: "Farm Vehicle" },
        { code: "G", emoji: "🔲", name: "Grid Square (6 digit)" },
        { code: "H", emoji: "🏨", name: "Hotel" },
        { code: "I", emoji: "📶", name: "TCP/IP on Air" },
        { code: "J", emoji: "⬜", name: "Undefined" },
        { code: "K", emoji: "🏫", name: "School" },
        { code: "L", emoji: "💻", name: "PC User" },
        { code: "M", emoji: "🍎", name: "MacAPRS" },
        { code: "N", emoji: "📰", name: "NTS Station" },
        { code: "O", emoji: "🎈", name: "Balloon" },
        { code: "P", emoji: "🚔", name: "Police Car" },
        { code: "Q", emoji: "⬜", name: "TBD" },
        { code: "R", emoji: "🚐", name: "Rec Vehicle" },
        { code: "S", emoji: "🚀", name: "Shuttle" },
        { code: "T", emoji: "📺", name: "SSTV" },
        { code: "U", emoji: "🚌", name: "Bus" },
        { code: "V", emoji: "📹", name: "ATV (Amateur TV)" },
        { code: "W", emoji: "🌦️", name: "National WX Svc Site" },
        { code: "X", emoji: "🚁", name: "Helicopter" },
        { code: "Y", emoji: "⛵", name: "Yacht (sail)" },
        { code: "Z", emoji: "💻", name: "WinAPRS" },
        { code: "[", emoji: "🧑", name: "Human / Person" },
        { code: "\\", emoji: "🔺", name: "Triangle (DF)" },
        { code: "]", emoji: "📬", name: "Mail / Post Office" },
        { code: "^", emoji: "✈️", name: "Large Aircraft" },
        { code: "_", emoji: "🌤️", name: "Weather Station (blue)" },
        { code: "`", emoji: "📡", name: "Dish Antenna" },
        { code: "a", emoji: "🚑", name: "Ambulance" },
        { code: "b", emoji: "🚲", name: "Bike" },
        { code: "c", emoji: "🏗️", name: "Incident Command Post" },
        { code: "d", emoji: "🧑‍🚒", name: "Fire Dept" },
        { code: "e", emoji: "🐴", name: "Horse" },
        { code: "f", emoji: "🚒", name: "Fire Truck" },
        { code: "g", emoji: "🛩️", name: "Glider" },
        { code: "h", emoji: "🏥", name: "Hospital" },
        { code: "i", emoji: "🏝️", name: "IOTA" },
        { code: "j", emoji: "🚙", name: "Jeep" },
        { code: "k", emoji: "🚚", name: "Truck" },
        { code: "l", emoji: "💻", name: "Laptop" },
        { code: "m", emoji: "📡", name: "Mic-E Repeater" },
        { code: "n", emoji: "📍", name: "Node" },
        { code: "o", emoji: "🏛️", name: "EOC" },
        { code: "p", emoji: "🐕", name: "Rover / Dog" },
        { code: "q", emoji: "🔲", name: "Grid Sq (above 128m)" },
        { code: "r", emoji: "📡", name: "Repeater" },
        { code: "s", emoji: "🚢", name: "Ship (power boat)" },
        { code: "t", emoji: "🛑", name: "Truck Stop" },
        { code: "u", emoji: "🚛", name: "Truck (18-wheeler)" },
        { code: "v", emoji: "🚐", name: "Van" },
        { code: "w", emoji: "💧", name: "Water Station" },
        { code: "x", emoji: "🐧", name: "xAPRS (Unix)" },
        { code: "y", emoji: "📡", name: "Yagi @ QTH" },
        { code: "z", emoji: "⬜", name: "TBD" },
        { code: "{", emoji: "⬜", name: "Undefined" },
        { code: "|", emoji: "🔀", name: "TNC Stream Switch" },
        { code: "}", emoji: "⬜", name: "Undefined" },
        { code: "~", emoji: "🔀", name: "TNC Stream Switch" },
    ],
    // ─── Alternate Symbol Table "\" ────────────────────────────────────
    "\\": [
        { code: "!", emoji: "🚨", name: "EMERGENCY" },
        { code: '"', emoji: "⬜", name: "Reserved" },
        { code: "#", emoji: "📡", name: "Overlay Digi (green)" },
        { code: "$", emoji: "🏦", name: "Bank / ATM" },
        { code: "%", emoji: "⚡", name: "Power Plant" },
        { code: "&", emoji: "🔷", name: "IGate / Gateway" },
        { code: "'", emoji: "💥", name: "Crash / Incident Site" },
        { code: "(", emoji: "☁️", name: "Cloudy" },
        { code: ")", emoji: "🎯", name: "Firenet MEO" },
        { code: "*", emoji: "❄️", name: "AVAIL (Snow→` ovly S)" },
        { code: "+", emoji: "⛪", name: "Church" },
        { code: ",", emoji: "👧", name: "Girl Scouts" },
        { code: "-", emoji: "🏡", name: "House (HF)" },
        { code: ".", emoji: "❓", name: "Ambiguous" },
        { code: "/", emoji: "📍", name: "Waypoint Destination" },
        { code: "0", emoji: "🔵", name: "Circle (IRLP/Echolink)" },
        { code: "1", emoji: "⬜", name: "AVAIL" },
        { code: "2", emoji: "⬜", name: "AVAIL" },
        { code: "3", emoji: "⬜", name: "AVAIL" },
        { code: "4", emoji: "⬜", name: "AVAIL" },
        { code: "5", emoji: "⬜", name: "AVAIL" },
        { code: "6", emoji: "⬜", name: "AVAIL" },
        { code: "7", emoji: "⬜", name: "AVAIL" },
        { code: "8", emoji: "📶", name: "802.11 Network Node" },
        { code: "9", emoji: "⛽", name: "Gas Station" },
        { code: ":", emoji: "⬜", name: "AVAIL (Hail→` ovly H)" },
        { code: ";", emoji: "🏕️", name: "Park / Picnic" },
        { code: "<", emoji: "🚩", name: "Advisory (WX flag)" },
        { code: "=", emoji: "🚂", name: "Overlay Rail" },
        { code: ">", emoji: "🚗", name: "Overlay Cars / Vehicles" },
        { code: "?", emoji: "ℹ️", name: "Info Kiosk" },
        { code: "@", emoji: "🌀", name: "Hurricane / Trop Storm" },
        { code: "A", emoji: "📦", name: "Overlay BOX (DTMF/RFID)" },
        { code: "B", emoji: "⬜", name: "AVAIL (BlwngSnow→E ovly B)" },
        { code: "C", emoji: "⚓", name: "Coast Guard" },
        { code: "D", emoji: "🏪", name: "Depot" },
        { code: "E", emoji: "💨", name: "Smoke / Visibility" },
        { code: "F", emoji: "⬜", name: "AVAIL (FrzngRain→` ovly F)" },
        { code: "G", emoji: "⬜", name: "AVAIL (SnowShwr→I ovly S)" },
        { code: "H", emoji: "🌫️", name: "Haze / Hazards" },
        { code: "I", emoji: "🌧️", name: "Rain Shower" },
        { code: "J", emoji: "⬜", name: "AVAIL (Lightning→I ovly L)" },
        { code: "K", emoji: "📻", name: "Kenwood HT" },
        { code: "L", emoji: "🗼", name: "Lighthouse" },
        { code: "M", emoji: "🎖️", name: "MARS" },
        { code: "N", emoji: "🧭", name: "Navigation Buoy" },
        { code: "O", emoji: "🚀", name: "Rocket / Overlay Balloon" },
        { code: "P", emoji: "🅿️", name: "Parking" },
        { code: "Q", emoji: "💥", name: "Quake" },
        { code: "R", emoji: "🍽️", name: "Restaurant" },
        { code: "S", emoji: "🛰️", name: "Satellite / Pacsat" },
        { code: "T", emoji: "⛈️", name: "Thunderstorm" },
        { code: "U", emoji: "☀️", name: "Sunny" },
        { code: "V", emoji: "📡", name: "VORTAC Nav Aid" },
        { code: "W", emoji: "🌤️", name: "NWS Site" },
        { code: "X", emoji: "💊", name: "Pharmacy Rx" },
        { code: "Y", emoji: "📻", name: "Radios / APRS Devices" },
        { code: "Z", emoji: "⬜", name: "AVAIL" },
        { code: "[", emoji: "🌪️", name: "Wall Cloud / Human (ovly)" },
        { code: "\\", emoji: "📍", name: "GPS Symbol (overlayable)" },
        { code: "]", emoji: "⬜", name: "AVAIL" },
        { code: "^", emoji: "✈️", name: "Overlay Aircraft" },
        { code: "_", emoji: "🌡️", name: "WX Site (green digi)" },
        { code: "`", emoji: "🌧️", name: "Rain (all types w ovly)" },
        { code: "a", emoji: "💎", name: "ARRL / ARES / WinLINK" },
        { code: "b", emoji: "⬜", name: "AVAIL (BlwngDst→E ovly)" },
        { code: "c", emoji: "🔺", name: "CD triangle RACES" },
        { code: "d", emoji: "📡", name: "DX Spot by Callsign" },
        { code: "e", emoji: "🌨️", name: "Sleet" },
        { code: "f", emoji: "🌪️", name: "Funnel Cloud" },
        { code: "g", emoji: "🚩", name: "Gale Flags" },
        { code: "h", emoji: "🏬", name: "Store / HAMFEST" },
        { code: "i", emoji: "📍", name: "BOX / Point of Interest" },
        { code: "j", emoji: "🚧", name: "WorkZone (Steam Shovel)" },
        { code: "k", emoji: "🚙", name: "Special Vehicle SUV" },
        { code: "l", emoji: "🗺️", name: "Areas (box/circles)" },
        { code: "m", emoji: "🪧", name: "Value Sign (3 digit)" },
        { code: "n", emoji: "🔺", name: "Overlay Triangle" },
        { code: "o", emoji: "⭕", name: "Small Circle" },
        { code: "p", emoji: "⬜", name: "AVAIL (PrtlyCldy→( ovly P)" },
        { code: "q", emoji: "⬜", name: "AVAIL" },
        { code: "r", emoji: "🚻", name: "Restrooms" },
        { code: "s", emoji: "🚢", name: "Overlay Ship / Boats" },
        { code: "t", emoji: "🌪️", name: "Tornado" },
        { code: "u", emoji: "🚚", name: "Overlay Truck" },
        { code: "v", emoji: "🚐", name: "Overlay Van" },
        { code: "w", emoji: "🌊", name: "Flooding / Avalanche" },
        { code: "x", emoji: "⚠️", name: "Wreck / Obstruction" },
        { code: "y", emoji: "⛈️", name: "Skywarn" },
        { code: "z", emoji: "🏠", name: "Overlay Shelter" },
        { code: "{", emoji: "⬜", name: "AVAIL (Fog→E ovly F)" },
        { code: "|", emoji: "🔀", name: "TNC Stream Switch" },
        { code: "}", emoji: "⬜", name: "AVAIL" },
        { code: "~", emoji: "🔀", name: "TNC Stream Switch" },
    ],
};

/**
 * APRS 1.2 Overlay Expansion definitions.
 * Key = alternate symbol code char, Value = { overlayChar: { emoji, name } }
 * Only commonly-defined overlays per symbols-new.txt (17 Mar 2021).
 * Any overlay not listed falls back to the base alternate symbol.
 */
const APRS_OVERLAYS = {
    // ─── AIRCRAFT: \^ ─────────────────────────────────────────────────
    "^": {
        "A": { emoji: "🤖", name: "Autonomous Aircraft" },
        "D": { emoji: "🛸", name: "Drone" },
        "E": { emoji: "⚡", name: "Electric Aircraft" },
        "H": { emoji: "🚁", name: "Hovercraft (air)" },
        "J": { emoji: "🛩️", name: "Jet" },
        "M": { emoji: "🚀", name: "Missile" },
        "P": { emoji: "🛩️", name: "Prop Aircraft" },
        "R": { emoji: "🛸", name: "Remotely Piloted" },
        "S": { emoji: "☀️", name: "Solar Powered Aircraft" },
        "V": { emoji: "🚁", name: "VTOL Aircraft" },
        "X": { emoji: "🛩️", name: "Experimental Aircraft" },
    },
    // ─── ADVISORY: \< ─────────────────────────────────────────────────
    "<": {},
    // ─── ATM / CURRENCY: \$ ───────────────────────────────────────────
    "$": {
        "U": { emoji: "💵", name: "US Dollars" },
        "L": { emoji: "💷", name: "British Pound" },
        "Y": { emoji: "💴", name: "Japanese Yen" },
    },
    // ─── ARRL / DIAMOND: \a ───────────────────────────────────────────
    "a": {
        "A": { emoji: "💎", name: "ARES" },
        "D": { emoji: "💎", name: "D-STAR" },
        "G": { emoji: "💎", name: "RSGB" },
        "R": { emoji: "💎", name: "RACES" },
        "S": { emoji: "💎", name: "SATERN" },
        "W": { emoji: "💎", name: "WinLINK" },
        "Y": { emoji: "💎", name: "C4FM Yaesu Repeater" },
    },
    // ─── BALLOONS: \O ─────────────────────────────────────────────────
    "O": {
        "B": { emoji: "🎈", name: "Blimp" },
        "M": { emoji: "🎈", name: "Manned Balloon" },
        "T": { emoji: "🎈", name: "Tethered Balloon" },
        "C": { emoji: "🎈", name: "Constant Pressure Balloon" },
        "R": { emoji: "🎈", name: "Rockoon" },
        "W": { emoji: "🎈", name: "World-round Balloon" },
    },
    // ─── BOX SYMBOL: \A ───────────────────────────────────────────────
    "A": {
        "9": { emoji: "📦", name: "Mobile DTMF User" },
        "7": { emoji: "📦", name: "HT DTMF User" },
        "A": { emoji: "📦", name: "AllStar DTMF" },
        "D": { emoji: "📦", name: "D-Star Report" },
        "E": { emoji: "📦", name: "Echolink DTMF" },
        "H": { emoji: "📦", name: "House DTMF User" },
        "I": { emoji: "📦", name: "IRLP DTMF" },
        "R": { emoji: "📦", name: "RFID Report" },
        "X": { emoji: "📦", name: "OLPC Laptop XO" },
    },
    // ─── BUILDINGS: \h ────────────────────────────────────────────────
    "h": {
        "C": { emoji: "🏬", name: "Ham Club" },
        "E": { emoji: "🏬", name: "Electronics Store" },
        "F": { emoji: "🏬", name: "HamFest" },
        "H": { emoji: "🏬", name: "Hardware Store" },
    },
    // ─── CARS / VEHICLES: \> ──────────────────────────────────────────
    ">": {
        "3": { emoji: "🚗", name: "Tesla Model 3" },
        "B": { emoji: "🚗", name: "BEV (Battery EV)" },
        "D": { emoji: "🚗", name: "DIY Vehicle" },
        "E": { emoji: "🚗", name: "Ethanol Vehicle" },
        "F": { emoji: "🚗", name: "Fuelcell / Hydrogen" },
        "H": { emoji: "🚗", name: "Hybrid Vehicle" },
        "L": { emoji: "🚗", name: "Nissan Leaf" },
        "P": { emoji: "🚗", name: "PHEV (Plugin Hybrid)" },
        "S": { emoji: "🚗", name: "Solar Powered Vehicle" },
        "T": { emoji: "🚗", name: "Tesla" },
        "V": { emoji: "🚗", name: "Chevy Volt" },
        "X": { emoji: "🚗", name: "Tesla Model X" },
    },
    // ─── CIVIL DEFENSE / TRIANGLE: \c ─────────────────────────────────
    "c": {
        "D": { emoji: "🔺", name: "Decontamination" },
        "R": { emoji: "🔺", name: "RACES" },
        "S": { emoji: "🔺", name: "SATERN Mobile Canteen" },
    },
    // ─── CIRCLES: \0 ──────────────────────────────────────────────────
    "0": {
        "A": { emoji: "🔵", name: "AllStar Node" },
        "E": { emoji: "🔵", name: "Echolink Node" },
        "I": { emoji: "🔵", name: "IRLP Repeater" },
        "S": { emoji: "🔵", name: "Staging Area" },
        "V": { emoji: "🔵", name: "VOIP (Echolink+IRLP)" },
        "W": { emoji: "🔵", name: "WIRES" },
    },
    // ─── CRASH / INCIDENT: \' ─────────────────────────────────────────
    "'": {
        "A": { emoji: "💥", name: "Automobile Crash" },
        "H": { emoji: "💥", name: "Hazardous Incident" },
        "M": { emoji: "💥", name: "Multi-Vehicle Crash" },
        "P": { emoji: "💥", name: "Pileup" },
        "T": { emoji: "💥", name: "Truck Wreck" },
    },
    // ─── DEPOTS: \D ───────────────────────────────────────────────────
    "D": {
        "A": { emoji: "🏪", name: "Airport Depot" },
        "B": { emoji: "🏪", name: "Bus Depot" },
        "F": { emoji: "🏪", name: "Ferry Landing" },
        "H": { emoji: "🏪", name: "Heliport" },
        "L": { emoji: "🏪", name: "Light Rail / Subway Depot" },
        "R": { emoji: "🏪", name: "Rail Depot" },
        "S": { emoji: "🏪", name: "Seaport Depot" },
    },
    // ─── DIGIPEATERS: \# ──────────────────────────────────────────────
    "#": {
        "1": { emoji: "📡", name: "WIDE1-1 Digipeater" },
        "A": { emoji: "📡", name: "Alternate Input Digi" },
        "E": { emoji: "📡", name: "Emergency Digi" },
        "I": { emoji: "📡", name: "IGate-equipped Digi" },
        "L": { emoji: "📡", name: "WIDEn-N Path Trapping Digi" },
        "P": { emoji: "📡", name: "PacComm Digi" },
        "S": { emoji: "📡", name: "SSn-N Digipeater" },
        "V": { emoji: "📡", name: "Viscous Digipeater" },
        "W": { emoji: "📡", name: "WIDEn-N + SSn-N Digi" },
        "X": { emoji: "📡", name: "Experimental Digi" },
    },
    // ─── EMERGENCY: \! ────────────────────────────────────────────────
    "!": {
        "E": { emoji: "🚨", name: "ELT / EPIRB" },
        "V": { emoji: "🚨", name: "Volcanic Eruption" },
    },
    // ─── EYEBALL / VISIBILITY: \E ─────────────────────────────────────
    "E": {
        "B": { emoji: "💨", name: "Blowing Snow" },
        "D": { emoji: "💨", name: "Blowing Dust/Sand" },
        "F": { emoji: "💨", name: "Fog" },
        "H": { emoji: "💨", name: "Haze" },
        "S": { emoji: "💨", name: "Smoke" },
    },
    // ─── GATEWAYS: \& ─────────────────────────────────────────────────
    "&": {
        "I": { emoji: "🔷", name: "IGate (generic)" },
        "L": { emoji: "🔷", name: "LoRa IGate" },
        "P": { emoji: "🔷", name: "PSKmail Node" },
        "R": { emoji: "🔷", name: "RX-only IGate" },
        "T": { emoji: "🔷", name: "TX IGate (1 hop)" },
        "W": { emoji: "🔷", name: "WIRES-X" },
        "2": { emoji: "🔷", name: "TX IGate (2 hop)" },
    },
    // ─── GPS DEVICES: \\ ──────────────────────────────────────────────
    "\\": {
        "A": { emoji: "📍", name: "Avmap G5" },
    },
    // ─── HAZARDS: \H ──────────────────────────────────────────────────
    "H": {
        "M": { emoji: "🌫️", name: "Methane Hazard" },
        "R": { emoji: "☢️", name: "Radiation Detector" },
        "W": { emoji: "☣️", name: "Hazardous Waste" },
        "X": { emoji: "☠️", name: "Skull & Crossbones" },
    },
    // ─── HOUSE: \- ────────────────────────────────────────────────────
    "-": {
        "5": { emoji: "🏡", name: "House (50 Hz)" },
        "6": { emoji: "🏡", name: "House (60 Hz)" },
        "B": { emoji: "🔋", name: "House (Battery / Off Grid)" },
        "C": { emoji: "🏡", name: "House (Combined Renew.)" },
        "E": { emoji: "🏡", name: "House (Emergency Power)" },
        "G": { emoji: "🏡", name: "House (Geothermal)" },
        "H": { emoji: "🏡", name: "House (Hydro)" },
        "O": { emoji: "🏡", name: "House (Operator Present)" },
        "S": { emoji: "☀️", name: "House (Solar)" },
        "W": { emoji: "🏡", name: "House (Wind Power)" },
    },
    // ─── HUMAN: \[ ────────────────────────────────────────────────────
    "[": {
        "B": { emoji: "👶", name: "Baby on Board" },
        "H": { emoji: "🥾", name: "Hiker" },
        "R": { emoji: "🏃", name: "Runner" },
        "S": { emoji: "⛷️", name: "Skier" },
    },
    // ─── NETWORK NODES: \8 ────────────────────────────────────────────
    "8": {
        "8": { emoji: "📶", name: "802.11 Node" },
        "G": { emoji: "📶", name: "802.11G Node" },
    },
    // ─── NWS / WEATHER: \W ────────────────────────────────────────────
    "W": {},
    // ─── PORTABLE: \; ─────────────────────────────────────────────────
    ";": {
        "F": { emoji: "🏕️", name: "Field Day" },
        "I": { emoji: "🏕️", name: "Islands on the Air" },
        "S": { emoji: "🏕️", name: "Summits on the Air" },
        "W": { emoji: "🏕️", name: "WOTA" },
    },
    // ─── POWER / ENERGY: \% ───────────────────────────────────────────
    "%": {
        "C": { emoji: "⚡", name: "Coal Power Plant" },
        "E": { emoji: "⚡", name: "Emergency Power" },
        "G": { emoji: "⚡", name: "Gas Turbine Plant" },
        "H": { emoji: "⚡", name: "Hydroelectric Plant" },
        "N": { emoji: "☢️", name: "Nuclear Power Plant" },
        "P": { emoji: "⚡", name: "Portable Power" },
        "R": { emoji: "⚡", name: "Renewable Power" },
        "S": { emoji: "☀️", name: "Solar Power Plant" },
        "T": { emoji: "⚡", name: "Geothermal Plant" },
        "W": { emoji: "⚡", name: "Wind Power Plant" },
    },
    // ─── RADIOS / APRS DEVICES: \Y ────────────────────────────────────
    "Y": {
        "A": { emoji: "📻", name: "Alinco Radio" },
        "B": { emoji: "📻", name: "Byonics TinyTrak" },
        "I": { emoji: "📻", name: "Icom Radio" },
        "K": { emoji: "📻", name: "Kenwood Radio" },
        "Y": { emoji: "📻", name: "Yaesu Radio" },
    },
    // ─── RAIL: \= ─────────────────────────────────────────────────────
    "=": {
        "B": { emoji: "🚂", name: "Bus-rail / Trolley" },
        "C": { emoji: "🚂", name: "Commuter Rail" },
        "D": { emoji: "🚂", name: "Diesel Train" },
        "E": { emoji: "🚂", name: "Electric Train" },
        "F": { emoji: "🚂", name: "Freight Train" },
        "G": { emoji: "🚂", name: "Gondola" },
        "H": { emoji: "🚄", name: "High Speed Rail" },
        "I": { emoji: "🚂", name: "Inclined Rail" },
        "L": { emoji: "🚂", name: "Elevated Rail" },
        "M": { emoji: "🚝", name: "Monorail" },
        "P": { emoji: "🚂", name: "Passenger Train" },
        "S": { emoji: "🚂", name: "Steam Train" },
        "T": { emoji: "🚂", name: "Rail Terminal" },
        "U": { emoji: "🚇", name: "Subway" },
        "X": { emoji: "🚂", name: "Excursion Train" },
    },
    // ─── RESTAURANT: \R ───────────────────────────────────────────────
    "R": {
        "7": { emoji: "🍽️", name: "7-Eleven" },
        "K": { emoji: "🍽️", name: "KFC" },
        "M": { emoji: "🍽️", name: "McDonalds" },
        "T": { emoji: "🍽️", name: "Taco Bell" },
    },
    // ─── SHELTERS: \z ─────────────────────────────────────────────────
    "z": {
        "C": { emoji: "🏠", name: "Clinic" },
        "E": { emoji: "🏠", name: "Emergency Power Shelter" },
        "G": { emoji: "🏠", name: "Government Building" },
        "M": { emoji: "🏠", name: "Morgue" },
        "T": { emoji: "🏠", name: "Triage" },
    },
    // ─── SHIPS: \s ────────────────────────────────────────────────────
    "s": {
        "6": { emoji: "🚢", name: "Shipwreck" },
        "B": { emoji: "🚢", name: "Pleasure Boat" },
        "C": { emoji: "🚢", name: "Cargo Ship" },
        "D": { emoji: "🚢", name: "Diving Vessel" },
        "E": { emoji: "🚢", name: "Emergency / Medical Ship" },
        "F": { emoji: "🚢", name: "Fishing Vessel" },
        "H": { emoji: "🚢", name: "High-speed Craft" },
        "J": { emoji: "🚢", name: "Jet Ski" },
        "L": { emoji: "🚢", name: "Law Enforcement Vessel" },
        "M": { emoji: "🚢", name: "Military Ship" },
        "O": { emoji: "🚢", name: "Oil Rig" },
        "P": { emoji: "🚢", name: "Pilot Boat" },
        "Q": { emoji: "🚢", name: "Torpedo" },
        "S": { emoji: "🚢", name: "Search & Rescue Ship" },
        "T": { emoji: "🚢", name: "Tug" },
        "U": { emoji: "🚢", name: "Submarine" },
        "W": { emoji: "🚢", name: "Wing-in-Ground / Hovercraft" },
        "X": { emoji: "🚢", name: "Passenger Ferry" },
        "Y": { emoji: "⛵", name: "Sailing Ship" },
    },
    // ─── SPECIAL VEHICLES: \k ─────────────────────────────────────────
    "k": {
        "4": { emoji: "🚙", name: "4x4" },
        "A": { emoji: "🚙", name: "ATV" },
    },
    // ─── TRUCKS: \u ───────────────────────────────────────────────────
    "u": {
        "B": { emoji: "🚚", name: "Bulldozer" },
        "C": { emoji: "🚚", name: "Chlorine Tanker" },
        "G": { emoji: "🚚", name: "Gas Truck" },
        "H": { emoji: "🚚", name: "Hazmat Truck" },
        "P": { emoji: "🚚", name: "Plow / Snowplow" },
        "T": { emoji: "🚚", name: "Tanker Truck" },
    },
    // ─── WATER: \w ────────────────────────────────────────────────────
    "w": {
        "A": { emoji: "🌊", name: "Avalanche" },
        "G": { emoji: "🌊", name: "Green Flood Gauge" },
        "M": { emoji: "🌊", name: "Mudslide" },
        "N": { emoji: "🌊", name: "Normal Flood Gauge" },
        "R": { emoji: "🌊", name: "Red Flood Gauge" },
        "S": { emoji: "🌊", name: "Snow Blockage" },
        "Y": { emoji: "🌊", name: "Yellow Flood Gauge" },
    },
    // ─── PRECIPITATION: \` ────────────────────────────────────────────
    "`": {
        "D": { emoji: "🌧️", name: "Drizzle" },
        "E": { emoji: "🌨️", name: "Sleet" },
        "F": { emoji: "🌧️", name: "Freezing Rain" },
        "H": { emoji: "🌧️", name: "Hail" },
        "R": { emoji: "🌧️", name: "Rain" },
        "S": { emoji: "❄️", name: "Snow" },
    },
    // ─── RAIN SHOWER (cloud variants): \I ─────────────────────────────
    "I": {
        "L": { emoji: "🌧️", name: "Lightning" },
        "R": { emoji: "🌧️", name: "Rain Shower" },
        "S": { emoji: "🌧️", name: "Snow Shower" },
    },
    // ─── CLOUDS: \( ───────────────────────────────────────────────────
    "(": {
        "F": { emoji: "☁️", name: "Funnel Cloud" },
        "P": { emoji: "☁️", name: "Partly Cloudy" },
        "W": { emoji: "☁️", name: "Wall Cloud" },
    },
};

/**
 * APRS Icon Picker controller.
 */
class APRSIconPicker {
    constructor() {
        this.currentTable = "/";
        this.selectedTable = "/";
        this.selectedCode = "#";
        this.modal = null;
        this.grid = null;
        this.searchInput = null;
    }

    init() {
        this.modal = document.getElementById('icon-picker-modal');
        this.grid = document.getElementById('icon-picker-grid');
        this.searchInput = document.getElementById('icon-search');

        if (!this.modal || !this.grid) return;

        // Open button
        document.getElementById('btn-open-icon-picker')?.addEventListener('click', (e) => {
            e.preventDefault();
            this.open();
        });

        // Close button
        document.getElementById('icon-picker-close')?.addEventListener('click', () => {
            this.close();
        });

        // Click outside to close
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });

        // Tab switching
        document.querySelectorAll('.icon-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this.currentTable = tab.dataset.table;
                document.querySelectorAll('.icon-tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                this.renderGrid();
            });
        });

        // Search
        this.searchInput?.addEventListener('input', () => {
            this.renderGrid();
        });

        // ESC to close
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.style.display !== 'none') {
                this.close();
            }
        });
    }

    open() {
        // Read current values
        this.selectedTable = document.getElementById('cfg-symbol-table')?.value || '/';
        this.selectedCode = document.getElementById('cfg-symbol-code')?.value || '#';
        this.currentTable = this.selectedTable;

        // Set active tab
        document.querySelectorAll('.icon-tab').forEach(t => {
            t.classList.toggle('active', t.dataset.table === this.currentTable);
        });

        if (this.searchInput) this.searchInput.value = '';
        this.renderGrid();
        this.modal.style.display = 'flex';
        this.searchInput?.focus();
    }

    close() {
        this.modal.style.display = 'none';
    }

    renderGrid() {
        const symbols = APRS_SYMBOLS[this.currentTable] || [];
        const search = (this.searchInput?.value || '').toLowerCase().trim();

        const filtered = search
            ? symbols.filter(s => s.name.toLowerCase().includes(search) || s.code === search)
            : symbols;

        this.grid.innerHTML = '';

        if (filtered.length === 0) {
            this.grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:var(--text-muted);padding:20px;">No matching symbols</div>';
            return;
        }

        filtered.forEach(sym => {
            const cell = document.createElement('div');
            cell.className = 'icon-cell';
            if (this.currentTable === this.selectedTable && sym.code === this.selectedCode) {
                cell.classList.add('selected');
            }

            const spriteImg = getAPRSSpriteHTML(this.currentTable, sym.code, 28);

            cell.innerHTML = `
                <span class="icon-cell-emoji">${spriteImg}</span>
                <span class="icon-cell-name" title="${sym.name}">${sym.name}</span>
                <span class="icon-cell-code">${this.currentTable}${sym.code}</span>
            `;

            cell.addEventListener('click', () => {
                this.selectSymbol(this.currentTable, sym.code, sym.emoji, sym.name);
            });

            this.grid.appendChild(cell);
        });
    }

    selectSymbol(table, code, emoji, name) {
        this.selectedTable = table;
        this.selectedCode = code;

        // Update hidden fields
        const tableEl = document.getElementById('cfg-symbol-table');
        const codeEl = document.getElementById('cfg-symbol-code');
        if (tableEl) tableEl.value = table;
        if (codeEl) codeEl.value = code;

        // Update preview with sprite
        const previewEl = document.getElementById('icon-picker-preview');
        const labelEl = document.getElementById('icon-picker-label');
        if (previewEl) previewEl.innerHTML = getAPRSSpriteHTML(table, code, 32);
        if (labelEl) labelEl.textContent = name;

        // Update selection info
        const infoEl = document.getElementById('icon-picker-selection');
        if (infoEl) infoEl.textContent = `Selected: ${name} (${table}${code})`;

        // Highlight in grid
        this.grid.querySelectorAll('.icon-cell').forEach(c => c.classList.remove('selected'));
        const cells = this.grid.querySelectorAll('.icon-cell');
        cells.forEach(c => {
            const codeSpan = c.querySelector('.icon-cell-code');
            if (codeSpan && codeSpan.textContent === `${table}${code}`) {
                c.classList.add('selected');
            }
        });

        // Close after short delay for visual feedback
        setTimeout(() => this.close(), 200);
    }

    /**
     * Update the preview from current config values (called when settings load).
     */
    updatePreviewFromConfig() {
        const table = document.getElementById('cfg-symbol-table')?.value || '/';
        const code = document.getElementById('cfg-symbol-code')?.value || '#';

        const symbols = APRS_SYMBOLS[table] || [];
        const sym = symbols.find(s => s.code === code);

        const previewEl = document.getElementById('icon-picker-preview');
        const labelEl = document.getElementById('icon-picker-label');

        if (previewEl) previewEl.innerHTML = getAPRSSpriteHTML(table, code, 32);
        if (sym) {
            if (labelEl) labelEl.textContent = sym.name;
        } else {
            if (labelEl) labelEl.textContent = `${table}${code}`;
        }
    }
}

// Global instance
window.pvIconPicker = new APRSIconPicker();

/* ── Sprite Sheet Support ────────────────────────────────────────────
 * Primary table → /static/icons/allicons.png   (6 cols × 16 rows, 16×16)
 * Alternate table → /static/icons/allicon2.png  (same layout)
 * Symbol codes '!' (ASCII 33) through '~' (ASCII 126) = 94 symbols.
 * Index = charCode − 33;  col = index % 6;  row = floor(index / 6)
 */
const APRS_SPRITE = {
    primary:  '/static/icons/allicons.png',
    alternate: '/static/icons/allicon2.png',
    cellSize: 16,
    cols: 6,
};

/**
 * Get CSS inline style for rendering an APRS symbol from the sprite sheet.
 * Returns an object { url, x, y } or null if the code is out of range.
 *
 * Sprite layout follows the standard APRS hex-table arrangement:
 *   Column = high nibble of ASCII code minus 2  (0x2_→col 0 … 0x7_→col 5)
 *   Row    = low nibble of ASCII code           (0x_0→row 0 … 0x_F→row 15)
 *
 * @param {string} table  "/", "\\", or overlay character
 * @param {string} code   single ASCII character
 * @returns {{ url: string, x: number, y: number } | null}
 */
function getAPRSSpritePosition(table, code) {
    if (!code || code.length !== 1) return null;
    const ch = code.charCodeAt(0);
    if (ch < 0x21 || ch > 0x7E) return null;
    const col = Math.floor(ch / 16) - 2;   // high nibble – 2
    const row = ch % 16;                    // low nibble
    const x = col * APRS_SPRITE.cellSize;
    const y = row * APRS_SPRITE.cellSize;
    const url = (table === '/') ? APRS_SPRITE.primary : APRS_SPRITE.alternate;
    return { url, x, y };
}

/**
 * Build an inline HTML string for displaying an APRS symbol sprite.
 * @param {string} table  "/", "\\", or overlay character
 * @param {string} code   single ASCII character
 * @param {number} [size=16] display size in pixels
 * @returns {string} HTML string (empty <div> with background sprite, or emoji fallback)
 */
function getAPRSSpriteHTML(table, code, size) {
    size = size || 16;
    const pos = getAPRSSpritePosition(table, code);
    if (!pos) {
        const emoji = getAPRSEmoji(table, code);
        return `<span class="aprs-emoji-fallback" style="font-size:${size}px;line-height:${size}px;">${emoji}</span>`;
    }
    const scale = size / APRS_SPRITE.cellSize;
    const bgW = 96 * scale;
    const bgH = 256 * scale;
    const bgX = pos.x * scale;
    const bgY = pos.y * scale;
    return `<div class="aprs-sprite" style="width:${size}px;height:${size}px;background:url('${pos.url}') no-repeat -${bgX}px -${bgY}px;background-size:${bgW}px ${bgH}px;"></div>`;
}

/**
 * Detect whether a table character is an overlay on the alternate table.
 * Overlay chars are 0-9, A-Z, or a-z (anything that isn't "/" or "\").
 * @param {string} table
 * @returns {boolean}
 */
function _isOverlayTable(table) {
    return table && table !== '/' && table !== '\\';
}

/**
 * Quick lookup: get the emoji for an APRS symbol table + code.
 * Supports primary "/", alternate "\", and overlay (0-9, A-Z, a-z) tables.
 * Falls back to generic pin if not found.
 * @param {string} table  "/", "\\", or overlay character
 * @param {string} code   single ASCII character
 * @returns {string} emoji character(s)
 */
function getAPRSEmoji(table, code) {
    // Primary table
    if (table === '/') {
        const s = APRS_SYMBOLS['/'].find(e => e.code === code);
        if (s) return s.emoji;
        return '📍';
    }
    // Alternate table (plain or overlay)
    if (table === '\\') {
        const s = APRS_SYMBOLS['\\'].find(e => e.code === code);
        if (s) return s.emoji;
        return '📍';
    }
    // Overlay on alternate symbol — check APRS_OVERLAYS first
    if (_isOverlayTable(table)) {
        const overlays = APRS_OVERLAYS[code];
        const ovlChar = table.toUpperCase();
        if (overlays && overlays[ovlChar]) return overlays[ovlChar].emoji;
        // Fall back to base alternate symbol
        const s = APRS_SYMBOLS['\\'].find(e => e.code === code);
        if (s) return s.emoji;
    }
    return '📍'; // generic fallback
}

/**
 * Get the human-readable name for an APRS symbol.
 * Supports primary "/", alternate "\", and overlay (0-9, A-Z, a-z) tables.
 * @param {string} table  "/", "\\", or overlay character
 * @param {string} code   single ASCII character
 * @returns {string}
 */
function getAPRSSymbolName(table, code) {
    if (table === '/') {
        const s = APRS_SYMBOLS['/'].find(e => e.code === code);
        if (s) return s.name;
        return `/${code}`;
    }
    if (table === '\\') {
        const s = APRS_SYMBOLS['\\'].find(e => e.code === code);
        if (s) return s.name;
        return `\\${code}`;
    }
    if (_isOverlayTable(table)) {
        const overlays = APRS_OVERLAYS[code];
        const ovlChar = table.toUpperCase();
        if (overlays && overlays[ovlChar]) return overlays[ovlChar].name;
        // Fall back to base alternate name + overlay indicator
        const s = APRS_SYMBOLS['\\'].find(e => e.code === code);
        if (s) return `${s.name} [${table}]`;
        return `\\${code} [${table}]`;
    }
    return `${table}${code}`;
}

/**
 * Station type categories for filtering.
 * Maps APRS symbol table+code to category strings.
 * Overlay tables (0-9, A-Z) are treated like alternate "\\" for category matching.
 */
const APRS_CATEGORIES = {
    'weather':     { label: '🌤️ Weather',       match: (t, c) => {
        if (c === '_') return true; // WX station (both tables)
        if (c === 'W' && t !== '/') return true; // NWS site (alt)
        if (t === '/' && c === 'W') return true; // National WX Service Site
        const altCode = t !== '/' ? c : '';
        return 'EHITU`(/<@'.includes(altCode) && t !== '/';
        // E=Smoke/vis, H=Haze, I=RainShower, T=Thunderstorm, U=Sunny, `=Rain
        // (=Cloudy, <=Advisory, @=Hurricane
    }},
    'digipeater':  { label: '📡 Digipeater',     match: (t, c) => c === '#' },
    'igate':       { label: '🔷 IGate/Gateway',   match: (t, c) => c === '&' || (t === '/' && c === 'I') },
    'vehicle':     { label: '🚗 Vehicle',        match: (t, c) => {
        // Primary cars/vehicles: >, j, <, k, =, R, u, v, * (snowmobile)
        if (t === '/') return '>j<k=Ruv*'.includes(c);
        // Alternate vehicles: >, k, u, v, = (rail overlays)
        return '>kuv='.includes(c);
    }},
    'aircraft':    { label: '✈️ Aircraft',        match: (t, c) => c === "'" || c === '^' || c === 'g' || (t === '/' && c === 'X') },
    'maritime':    { label: '⛵ Maritime',        match: (t, c) => c === 'C' || c === 'Y' || c === 's' || (t !== '/' && c === 'N') },
    'person':      { label: '🧑 Person/Portable', match: (t, c) => c === '[' || (t === '/' && c === 'b') || (t === '/' && c === 'e') || c === ';' },
    'infrastructure': { label: '🗼 Infrastructure', match: (t, c) => {
        if (t === '/') return 'rnm'.includes(c);
        return 'L8'.includes(c); // Lighthouse, network nodes
    }},
    'house':       { label: '🏠 House/Fixed',    match: (t, c) => c === '-' || (t === '/' && c === 'y') || (t !== '/' && c === 'z') },
    'emergency':   { label: '🚨 Emergency',      match: (t, c) => {
        if (t === '/') return '!aPdfo'.includes(c); // Police, ambulance, police car, fire dept, fire truck, EOC
        return c === '!' || c === 'Q'; // Emergency, Quake
    }},
    'other':       { label: '📍 Other',          match: () => true }, // catch-all
};

/** Ordered category keys (excluding catch-all 'other'). */
const APRS_CATEGORY_ORDER = [
    'weather', 'digipeater', 'igate', 'vehicle', 'aircraft',
    'maritime', 'person', 'infrastructure', 'house', 'emergency', 'other'
];

/**
 * Determine the category key for a station given its APRS symbol.
 * Overlay table characters (0-9, A-Z, a-z) are treated as alternate table.
 * @param {string} table  "/", "\\", or overlay character
 * @param {string} code   single ASCII character
 * @returns {string} category key
 */
function getAPRSCategory(table, code) {
    // Normalize: overlay tables behave like alternate for category purposes
    const effectiveTable = _isOverlayTable(table) ? '\\' : table;
    for (const key of APRS_CATEGORY_ORDER) {
        if (key === 'other') continue; // skip catch-all
        if (APRS_CATEGORIES[key].match(effectiveTable, code)) return key;
    }
    return 'other';
}

/**
 * Get the display label for a category key.
 */
function getAPRSCategoryLabel(key) {
    return (APRS_CATEGORIES[key] || APRS_CATEGORIES['other']).label;
}
