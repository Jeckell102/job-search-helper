"""Conservative U.S. eligibility from the posting location, never employer HQ.

Country names/codes are bundled from ISO 3166 (Debian iso-codes); no network
lookup or optional package is needed. Unknown/mixed locations go to review.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

# State abbreviations that also name countries must not reject U.S. cities.
STATE_CODES = frozenset("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
STATE_NAMES = ("Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming", "District of Columbia")


def _normal(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).casefold().split())


@dataclass(frozen=True)
class LocationCheck:
    status: str  # us, non_us, unknown
    evidence: str

    @property
    def rejection_reason(self):
        if self.status == "non_us":
            return "Location exclusion: posting is outside the U.S. (" + self.evidence + ")."
        return None


def _place(value):
    text = _normal(value)
    text = re.sub(r"\bturkiye\b", "Turkey", text, flags=re.I).casefold()
    # U.S. territories are not foreign countries. Keep them for explicit review
    # rather than silently equating them with states/DC or excluding them.
    if re.search(r"\b(?:guam|puerto rico|american samoa|northern mariana|u\.?s\.? virgin islands)\b|(?:^|[, -])(?:gu|pr|as|mp|vi)(?:$|[, )])", text):
        return LocationCheck("unknown", "U.S. territory: confirm location preference")

    match = _COUNTRY_PATTERN.search(text)
    country = match.group(0) if match else None
    # Codes only count as location components, never as substrings in a city.
    # Ambiguous country/state codes (CA, IN, DE, IL, etc.) stay non-rejecting.
    for token in re.findall(r"(?:^|[, (])([A-Z]{2,3})(?=$|[, )]|\s*[-:])", value):
        if token in COUNTRY_CODES and token not in STATE_CODES:
            country = country or token

    explicit_us = bool(re.search(
        r"\bunited states(?: of america)?\b|\busa\b|\bu\.s\.(?:a\.?)?|"
        r"^us(?=$|[ ,(-])|(?:,\s*|[-(]\s*)us\b|\bus\s*[- ]remote\b|"
        r"\bremote\s+(?:(?:within|in|from)\s+)?us\b", text))
    # A state component, not a word inside 'New Delhi' or 'Washington team'.
    state = bool(re.search(r"(?:,\s*|\s-\s|\s)(?:" + "|".join(STATE_CODES) + r")(?:$|[ ,()])", value))
    state = state or any(re.search(r"(?:^|,\s*)" + re.escape(_normal(name)) + r"(?:$|[ ,()])", text)
                              for name in STATE_NAMES if name != "Georgia")
    if country:
        # Free text cannot distinguish a country from a namesake U.S. city
        # (Lebanon, OH), or a foreign region code from a U.S. state. Preserve
        # both signals for review; complete structured country evidence is
        # handled separately by check_posting_location.
        if explicit_us or state:
            return LocationCheck("unknown", "Mixed or conflicting U.S./overseas location: " + value)
        return LocationCheck("non_us", value)
    if explicit_us or state:
        return LocationCheck("us", value)
    return LocationCheck("unknown", "Location requires verification: " + (value or "not supplied"))


def check_location(value):
    """Reject only when every listed alternative is clearly overseas.

    Remote/hybrid is an arrangement, not proof of U.S. eligibility. Descriptions
    are intentionally not scanned: travel, customers and HQ are not job bases.
    """
    value = str(value or "").strip()
    if not value:
        return LocationCheck("unknown", "Location not supplied; verify U.S. eligibility")
    parts = [p.strip() for p in re.split(r"[;\n|/]|\s+or\s+", value, flags=re.I) if p.strip()]
    checks = [_place(p) for p in parts]
    if any(c.status == "us" for c in checks):
        return LocationCheck("us", value)
    if checks and all(c.status == "non_us" for c in checks):
        return LocationCheck("non_us", value)
    return LocationCheck("unknown", "; ".join(c.evidence for c in checks))


def check_posting_location(posting):
    """Use complete, official country-scope evidence without guessing cities."""
    result = check_location(posting.get("location"))
    # Explicit U.S. alternatives and territories always survive a conflicting
    # primary-country label. A country-scoped listing must cover all options.
    if result.status == "us" or "U.S. territory" in result.evidence:
        return result
    if posting.get("location_country") and posting.get("location_has_alternatives") is False:
        primary = check_location(posting["location_country"])
        if primary.status == "non_us" and check_location(posting.get("location_primary")).status == "us":
            return LocationCheck("unknown", "Conflicting structured country and U.S. location: " + str(posting.get("location")))
        if primary.status in ("us", "non_us"):
            return LocationCheck(primary.status, str(posting.get("location") or ""))
    scope = posting.get("location_country_scope") or {}
    if scope.get("source_url") and type(scope.get("us_eligible")) is bool:
        if scope["us_eligible"]:
            return LocationCheck("us", str(posting.get("location") or ""))
        return LocationCheck("non_us", str(posting.get("location") or "") +
                             "; official country filter confirms no U.S. alternative")
    return result

COUNTRY_NAMES = ('United Kingdom of Great Britain and Northern Ireland',
 'Hong Kong Special Administrative Region of China', 'Democratic Republic of Sao Tome and Principe',
 'Macao Special Administrative Region of China', 'Saint Helena, Ascension and Tristan da Cunha',
 'South Georgia and the South Sandwich Islands', 'Democratic Socialist Republic of Sri Lanka',
 'Federal Democratic Republic of Ethiopia', "People's Democratic Republic of Algeria",
 "Korea, Democratic People's Republic of", 'Congo, The Democratic Republic of the',
 "Democratic People's Republic of Korea", 'Independent State of Papua New Guinea',
 'Federal Democratic Republic of Nepal', 'Democratic Republic of Timor-Leste',
 'Republic of Bosnia and Herzegovina', 'Heard Island and McDonald Islands',
 'Venezuela, Bolivarian Republic of', 'Bolivarian Republic of Venezuela',
 'Bonaire, Sint Eustatius and Saba', "Lao People's Democratic Republic",
 'Republic of the Marshall Islands', 'Saint Vincent and the Grenadines',
 'Bolivia, Plurinational State of', 'Islamic Republic of Afghanistan',
 'Micronesia, Federated States of', "People's Republic of Bangladesh",
 'Republic of Trinidad and Tobago', 'British Indian Ocean Territory',
 'Federated States of Micronesia', 'Islamic Republic of Mauritania',
 'Plurinational State of Bolivia', 'Socialist Republic of Viet Nam',
 'Federative Republic of Brazil', 'Holy See (Vatican City State)', 'Principality of Liechtenstein',
 'Republic of Equatorial Guinea', 'Islamic Republic of Pakistan', 'Tanzania, United Republic of',
 'Commonwealth of the Bahamas', 'Eastern Republic of Uruguay', 'Falkland Islands (Malvinas)',
 'Federal Republic of Germany', 'Federal Republic of Nigeria', 'Federal Republic of Somalia',
 'French Southern Territories', 'Hashemite Kingdom of Jordan', 'Republic of North Macedonia',
 'Republic of the Philippines', 'United Republic of Tanzania', 'Independent State of Samoa',
 'Kingdom of the Netherlands', "People's Republic of China", 'Saint Martin (French part)',
 'Grand Duchy of Luxembourg', 'Iran, Islamic Republic of', "Republic of Côte d'Ivoire",
 'Republic of Guinea-Bissau', 'Saint Pierre and Miquelon', 'Sint Maarten (Dutch part)',
 'Taiwan, Province of China', 'Central African Republic', 'Commonwealth of Dominica',
 'Islamic Republic of Iran', 'Republic of Sierra Leone', 'Republic of South Africa',
 'Turks and Caicos Islands', 'Cocos (Keeling) Islands', 'Kingdom of Saudi Arabia',
 'Principality of Andorra', 'Republic of El Salvador', 'Republic of South Sudan',
 'Virgin Islands, British', 'Arab Republic of Egypt', 'Bosnia and Herzegovina',
 'British Virgin Islands', 'Principality of Monaco', 'Republic of Azerbaijan',
 'Republic of Cabo Verde', 'Republic of Costa Rica', 'Republic of Kazakhstan',
 'Republic of Madagascar', 'Republic of Mozambique', 'Republic of San Marino',
 'Republic of Seychelles', 'Republic of Tajikistan', 'Republic of Uzbekistan',
 'Republic of the Gambia', 'Svalbard and Jan Mayen', 'the State of Palestine',
 'Republic of Guatemala', 'Republic of Indonesia', 'Republic of Lithuania', 'Republic of Mauritius',
 'Republic of Nicaragua', 'Republic of Singapore', 'Republic of the Congo', 'Republic of the Niger',
 'Republic of the Sudan', 'Saint Kitts and Nevis', 'Sao Tome and Principe', 'United Mexican States',
 'Moldova, Republic of', 'Republic of Botswana', 'Republic of Bulgaria', 'Republic of Cameroon',
 'Republic of Colombia', 'Republic of Djibouti', 'Republic of Honduras', 'Republic of Kiribati',
 'Republic of Maldives', 'Republic of Paraguay', 'Republic of Slovenia', 'Republic of Suriname',
 'Republic of Zimbabwe', 'Syrian Arab Republic', 'Union of the Comoros', 'United Arab Emirates',
 'the State of Eritrea', 'Antigua and Barbuda', 'Kingdom of Cambodia', 'Kingdom of Eswatini',
 'Kingdom of Thailand', 'Palestine, State of', 'Portuguese Republic', 'Republic of Albania',
 'Republic of Armenia', 'Republic of Austria', 'Republic of Belarus', 'Republic of Burundi',
 'Republic of Croatia', 'Republic of Ecuador', 'Republic of Estonia', 'Republic of Finland',
 'Republic of Iceland', 'Republic of Liberia', 'Republic of Moldova', 'Republic of Myanmar',
 'Republic of Namibia', 'Republic of Senegal', 'Republic of Tunisia', 'Republic of Vanuatu',
 'Swiss Confederation', 'Trinidad and Tobago', 'Argentine Republic', 'Dominican Republic',
 'Kingdom of Bahrain', 'Kingdom of Belgium', 'Kingdom of Denmark', 'Kingdom of Lesotho',
 'Kingdom of Morocco', 'Korea, Republic of', 'Republic of Angola', 'Republic of Cyprus',
 'Republic of Guinea', 'Republic of Guyana', 'Republic of Latvia', 'Republic of Malawi',
 'Republic of Panama', 'Republic of Poland', 'Republic of Serbia', 'Republic of Turkey',
 'Republic of Uganda', 'Republic of Zambia', 'Russian Federation', 'Brunei Darussalam',
 'Equatorial Guinea', 'Gabonese Republic', 'Hellenic Republic', 'Kingdom of Bhutan',
 'Kingdom of Norway', 'Kingdom of Sweden', 'Lebanese Republic', 'Republic of Benin',
 'Republic of Chile', 'Republic of Ghana', 'Republic of Haiti', 'Republic of India',
 'Republic of Kenya', 'Republic of Malta', 'Republic of Nauru', 'Republic of Palau',
 'Republic of Yemen', 'Rwandese Republic', 'Sultanate of Oman', 'Togolese Republic',
 'Wallis and Futuna', 'Christmas Island', 'French Polynesia', 'Italian Republic',
 'Kingdom of Spain', 'Kingdom of Tonga', 'Marshall Islands', 'Northern Ireland', 'Papua New Guinea',
 'Republic of Chad', 'Republic of Cuba', 'Republic of Fiji', 'Republic of Iraq', 'Republic of Mali',
 'Republic of Peru', 'Saint Barthélemy', 'French Republic', 'Kyrgyz Republic', 'North Macedonia',
 'Slovak Republic', 'Solomon Islands', 'State of Israel', 'State of Kuwait', 'Cayman Islands',
 'Czech Republic', 'Norfolk Island', 'State of Qatar', 'United Kingdom', 'Western Sahara',
 'Bouvet Island', "Côte d'Ivoire", 'Faroe Islands', 'French Guiana', 'Great Britain',
 'Guinea-Bissau', 'Liechtenstein', 'New Caledonia', 'Åland Islands', 'Burkina Faso', 'Cook Islands',
 'Saudi Arabia', 'Sierra Leone', 'South Africa', 'Turkmenistan', 'Afghanistan', 'El Salvador',
 'Isle of Man', 'Ivory Coast', 'Netherlands', 'New Zealand', 'North Korea', 'Philippines',
 'Saint Lucia', 'South Korea', 'South Sudan', 'Switzerland', 'Timor-Leste', 'Antarctica',
 'Azerbaijan', 'Bangladesh', 'Cabo Verde', 'Costa Rica', 'Guadeloupe', 'Kazakhstan', 'Kyrgyzstan',
 'Luxembourg', 'Madagascar', 'Martinique', 'Mauritania', 'Montenegro', 'Montserrat', 'Mozambique',
 'San Marino', 'Seychelles', 'Tajikistan', 'Uzbekistan', 'Argentina', 'Australia', 'Gibraltar',
 'Greenland', 'Guatemala', 'Hong Kong', 'Indonesia', 'Lithuania', 'Mauritius', 'Nicaragua',
 'Singapore', 'Sri Lanka', 'Venezuela', 'Anguilla', 'Barbados', 'Botswana', 'Bulgaria', 'Cambodia',
 'Cameroon', 'Colombia', 'Djibouti', 'Dominica', 'Eswatini', 'Ethiopia', 'Guernsey', 'Honduras',
 'Kiribati', 'Malaysia', 'Maldives', 'Mongolia', 'Pakistan', 'Paraguay', 'Pitcairn', 'Portugal',
 'Scotland', 'Slovakia', 'Slovenia', 'Suriname', 'Tanzania', 'Thailand', 'Viet Nam', 'Zimbabwe',
 'Albania', 'Algeria', 'Andorra', 'Armenia', 'Austria', 'Bahamas', 'Bahrain', 'Belarus', 'Belgium',
 'Bermuda', 'Bolivia', 'Burundi', 'Comoros', 'Croatia', 'Curaçao', 'Czechia', 'Denmark', 'Ecuador',
 'England', 'Eritrea', 'Estonia', 'Finland', 'Germany', 'Grenada', 'Hungary', 'Iceland', 'Ireland',
 'Jamaica', 'Lebanon', 'Lesotho', 'Liberia', 'Mayotte', 'Moldova', 'Morocco', 'Myanmar', 'Namibia',
 'Nigeria', 'Romania', 'Réunion', 'Senegal', 'Somalia', 'Tokelau', 'Tunisia', 'Ukraine', 'Uruguay',
 'Vanuatu', 'Vietnam', 'Angola', 'Belize', 'Bhutan', 'Brazil', 'Canada', 'Cyprus', 'France',
 'Gambia', 'Greece', 'Guinea', 'Guyana', 'Israel', 'Jersey', 'Jordan', 'Kuwait', 'Latvia', 'Malawi',
 'Mexico', 'Monaco', 'Norway', 'Panama', 'Poland', 'Russia', 'Rwanda', 'Serbia', 'Sweden', 'Taiwan',
 'Turkey', 'Tuvalu', 'Uganda', 'Zambia', 'Aruba', 'Benin', 'Chile', 'China', 'Congo', 'Egypt',
 'Gabon', 'Ghana', 'Haiti', 'India', 'Italy', 'Japan', 'Kenya', 'Libya', 'Macao', 'Macau', 'Malta',
 'Nauru', 'Nepal', 'Niger', 'Palau', 'Qatar', 'Samoa', 'Spain', 'Sudan', 'Tonga', 'Wales', 'Yemen',
 'Chad', 'Cuba', 'Fiji', 'Iraq', 'Mali', 'Niue', 'Oman', 'Peru', 'Togo', 'UAE', 'UK')

COUNTRY_CODES = frozenset(('ABW', 'AD', 'AE', 'AF', 'AFG', 'AG', 'AGO', 'AI', 'AIA', 'AL', 'ALA', 'ALB', 'AM', 'AND', 'AO', 'AQ', 'AR', 'ARE', 'ARG', 'ARM', 'AT', 'ATA', 'ATF', 'ATG', 'AU', 'AUS', 'AUT', 'AW', 'AX', 'AZ', 'AZE', 'BA', 'BB', 'BD', 'BDI', 'BE', 'BEL', 'BEN', 'BES', 'BF', 'BFA', 'BG', 'BGD', 'BGR', 'BH', 'BHR', 'BHS', 'BI', 'BIH', 'BJ', 'BL', 'BLM', 'BLR', 'BLZ', 'BM', 'BMU', 'BN', 'BO', 'BOL', 'BQ', 'BR', 'BRA', 'BRB', 'BRN', 'BS', 'BT', 'BTN', 'BV', 'BVT', 'BW', 'BWA', 'BY', 'BZ', 'CA', 'CAF', 'CAN', 'CC', 'CCK', 'CD', 'CF', 'CG', 'CH', 'CHE', 'CHL', 'CHN', 'CI', 'CIV', 'CK', 'CL', 'CM', 'CMR', 'CN', 'CO', 'COD', 'COG', 'COK', 'COL', 'COM', 'CPV', 'CR', 'CRI', 'CU', 'CUB', 'CUW', 'CV', 'CW', 'CX', 'CXR', 'CY', 'CYM', 'CYP', 'CZ', 'CZE', 'DE', 'DEU', 'DJ', 'DJI', 'DK', 'DM', 'DMA', 'DNK', 'DO', 'DOM', 'DZ', 'DZA', 'EC', 'ECU', 'EE', 'EG', 'EGY', 'EH', 'ER', 'ERI', 'ES', 'ESH', 'ESP', 'EST', 'ET', 'ETH', 'FI', 'FIN', 'FJ', 'FJI', 'FK', 'FLK', 'FM', 'FO', 'FR', 'FRA', 'FRO', 'FSM', 'GA', 'GAB', 'GB', 'GBR', 'GD', 'GE', 'GEO', 'GF', 'GG', 'GGY', 'GH', 'GHA', 'GI', 'GIB', 'GIN', 'GL', 'GLP', 'GM', 'GMB', 'GN', 'GNB', 'GNQ', 'GP', 'GQ', 'GR', 'GRC', 'GRD', 'GRL', 'GS', 'GT', 'GTM', 'GUF', 'GUY', 'GW', 'GY', 'HK', 'HKG', 'HM', 'HMD', 'HN', 'HND', 'HR', 'HRV', 'HT', 'HTI', 'HU', 'HUN', 'ID', 'IDN', 'IE', 'IL', 'IM', 'IMN', 'IN', 'IND', 'IO', 'IOT', 'IQ', 'IR', 'IRL', 'IRN', 'IRQ', 'IS', 'ISL', 'ISR', 'IT', 'ITA', 'JAM', 'JE', 'JEY', 'JM', 'JO', 'JOR', 'JP', 'JPN', 'KAZ', 'KE', 'KEN', 'KG', 'KGZ', 'KH', 'KHM', 'KI', 'KIR', 'KM', 'KN', 'KNA', 'KOR', 'KP', 'KR', 'KW', 'KWT', 'KY', 'KZ', 'LA', 'LAO', 'LB', 'LBN', 'LBR', 'LBY', 'LC', 'LCA', 'LI', 'LIE', 'LK', 'LKA', 'LR', 'LS', 'LSO', 'LT', 'LTU', 'LU', 'LUX', 'LV', 'LVA', 'LY', 'MA', 'MAC', 'MAF', 'MAR', 'MC', 'MCO', 'MD', 'MDA', 'MDG', 'MDV', 'ME', 'MEX', 'MF', 'MG', 'MH', 'MHL', 'MK', 'MKD', 'ML', 'MLI', 'MLT', 'MM', 'MMR', 'MN', 'MNE', 'MNG', 'MO', 'MOZ', 'MQ', 'MR', 'MRT', 'MS', 'MSR', 'MT', 'MTQ', 'MU', 'MUS', 'MV', 'MW', 'MWI', 'MX', 'MY', 'MYS', 'MYT', 'MZ', 'NA', 'NAM', 'NC', 'NCL', 'NE', 'NER', 'NF', 'NFK', 'NG', 'NGA', 'NI', 'NIC', 'NIU', 'NL', 'NLD', 'NO', 'NOR', 'NP', 'NPL', 'NR', 'NRU', 'NU', 'NZ', 'NZL', 'OM', 'OMN', 'PA', 'PAK', 'PAN', 'PCN', 'PE', 'PER', 'PF', 'PG', 'PH', 'PHL', 'PK', 'PL', 'PLW', 'PM', 'PN', 'PNG', 'POL', 'PRK', 'PRT', 'PRY', 'PS', 'PSE', 'PT', 'PW', 'PY', 'PYF', 'QA', 'QAT', 'RE', 'REU', 'RO', 'ROU', 'RS', 'RU', 'RUS', 'RW', 'RWA', 'SA', 'SAU', 'SB', 'SC', 'SD', 'SDN', 'SE', 'SEN', 'SG', 'SGP', 'SGS', 'SH', 'SHN', 'SI', 'SJ', 'SJM', 'SK', 'SL', 'SLB', 'SLE', 'SLV', 'SM', 'SMR', 'SN', 'SO', 'SOM', 'SPM', 'SR', 'SRB', 'SS', 'SSD', 'ST', 'STP', 'SUR', 'SV', 'SVK', 'SVN', 'SWE', 'SWZ', 'SX', 'SXM', 'SY', 'SYC', 'SYR', 'SZ', 'TC', 'TCA', 'TCD', 'TD', 'TF', 'TG', 'TGO', 'TH', 'THA', 'TJ', 'TJK', 'TK', 'TKL', 'TKM', 'TL', 'TLS', 'TM', 'TN', 'TO', 'TON', 'TR', 'TT', 'TTO', 'TUN', 'TUR', 'TUV', 'TV', 'TW', 'TWN', 'TZ', 'TZA', 'UA', 'UG', 'UGA', 'UKR', 'URY', 'UY', 'UZ', 'UZB', 'VA', 'VAT', 'VC', 'VCT', 'VE', 'VEN', 'VG', 'VGB', 'VN', 'VNM', 'VU', 'VUT', 'WF', 'WLF', 'WS', 'WSM', 'YE', 'YEM', 'YT', 'ZA', 'ZAF', 'ZM', 'ZMB', 'ZW', 'ZWE'))



_COUNTRY_PATTERN = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(_normal(n)) for n in COUNTRY_NAMES) + r")(?!\w)")
