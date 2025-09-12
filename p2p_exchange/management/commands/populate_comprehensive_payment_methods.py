from django.core.management.base import BaseCommand
from django.db import transaction
from p2p_exchange.models import P2PPaymentMethod
from users.models import Country, Bank

class Command(BaseCommand):
    help = 'Populate comprehensive payment methods for LATAM, US, and Spain'

    def handle(self, *args, **options):
        self.stdout.write('Populating comprehensive payment methods...')
        
        # Comprehensive payment methods by country
        payment_methods_data = {
            # ARGENTINA (AR)
            'AR': {
                'banks': [
                    ('banco_nacion', 'Banco de la Nación Argentina'),
                    ('banco_provincia', 'Banco Provincia'),
                    ('santander_rio', 'Santander Río'),
                    ('bbva_argentina', 'BBVA Argentina'),
                    ('banco_galicia', 'Banco Galicia'),
                    ('banco_macro', 'Banco Macro'),
                    ('hsbc_argentina', 'HSBC Argentina'),
                    ('banco_patagonia', 'Banco Patagonia'),
                    ('banco_ciudad', 'Banco Ciudad'),
                    ('icbc_argentina', 'ICBC Argentina'),
                ],
                'fintech': [
                    ('mercadopago_ar', 'Mercado Pago'),
                    ('uala', 'Ualá'),
                    ('brubank', 'Brubank'),
                    ('rebanking', 'Rebanking'),
                    ('naranja_x', 'Naranja X'),
                    ('personal_pay', 'Personal Pay'),
                    ('modo', 'MODO'),
                    ('belo', 'Belo'),
                    ('ripio', 'Ripio'),
                    ('lemon_cash', 'Lemon Cash'),
                ]
            },
            
            # BOLIVIA (BO)
            'BO': {
                'banks': [
                    ('banco_union', 'Banco Unión'),
                    ('banco_mercantil', 'Banco Mercantil Santa Cruz'),
                    ('banco_nacional', 'Banco Nacional de Bolivia'),
                    ('banco_bisa', 'Banco BISA'),
                    ('banco_credito', 'Banco de Crédito de Bolivia'),
                    ('banco_ganadero', 'Banco Ganadero'),
                    ('banco_economico', 'Banco Económico'),
                    ('banco_fie', 'Banco FIE'),
                    ('banco_fortaleza', 'Banco Fortaleza'),
                ],
                'fintech': [
                    ('billetera_movil', 'Billetera Móvil'),
                    ('e_fectivo', 'E-fectivo'),
                    ('tigo_money', 'Tigo Money'),
                    ('pagosnet', 'PagosNet'),
                ]
            },
            
            # BRAZIL (BR)
            'BR': {
                'banks': [
                    ('banco_do_brasil', 'Banco do Brasil'),
                    ('caixa', 'Caixa Econômica Federal'),
                    ('bradesco', 'Bradesco'),
                    ('itau', 'Itaú Unibanco'),
                    ('santander_brasil', 'Santander Brasil'),
                    ('banco_inter', 'Banco Inter'),
                    ('nubank', 'Nubank'),
                    ('banco_original', 'Banco Original'),
                    ('banco_pan', 'Banco Pan'),
                    ('c6_bank', 'C6 Bank'),
                    ('banco_safra', 'Banco Safra'),
                    ('btg_pactual', 'BTG Pactual'),
                ],
                'fintech': [
                    ('pix', 'PIX'),
                    ('picpay', 'PicPay'),
                    ('mercadopago_br', 'Mercado Pago'),
                    ('pagseguro', 'PagSeguro'),
                    ('paypal_br', 'PayPal'),
                    ('recargapay', 'RecargaPay'),
                    ('ame_digital', 'Ame Digital'),
                    ('pagbank', 'PagBank'),
                    ('neon', 'Neon'),
                    ('next', 'Next'),
                ]
            },
            
            # CHILE (CL)
            'CL': {
                'banks': [
                    ('banco_estado', 'BancoEstado'),
                    ('banco_chile', 'Banco de Chile'),
                    ('banco_santander_cl', 'Banco Santander Chile'),
                    ('banco_bci', 'Banco BCI'),
                    ('scotiabank_cl', 'Scotiabank Chile'),
                    ('banco_itau_cl', 'Banco Itaú Chile'),
                    ('banco_security', 'Banco Security'),
                    ('banco_falabella', 'Banco Falabella'),
                    ('banco_ripley', 'Banco Ripley'),
                    ('banco_consorcio', 'Banco Consorcio'),
                ],
                'fintech': [
                    ('mercadopago_cl', 'Mercado Pago'),
                    ('mach', 'MACH'),
                    ('fpay', 'Fpay'),
                    ('khipu', 'Khipu'),
                    ('flow', 'Flow'),
                    ('multicaja', 'Multicaja'),
                    ('redcompra', 'Redcompra'),
                    ('servipag', 'Servipag'),
                    ('webpay', 'Webpay Plus'),
                ]
            },
            
            # COLOMBIA (CO)
            'CO': {
                'banks': [
                    ('bancolombia', 'Bancolombia'),
                    ('banco_bogota', 'Banco de Bogotá'),
                    ('davivienda', 'Davivienda'),
                    ('bbva_colombia', 'BBVA Colombia'),
                    ('banco_occidente', 'Banco de Occidente'),
                    ('banco_popular', 'Banco Popular'),
                    ('banco_av_villas', 'Banco AV Villas'),
                    ('banco_caja_social', 'Banco Caja Social'),
                    ('citibank_co', 'Citibank Colombia'),
                    ('scotiabank_colpatria', 'Scotiabank Colpatria'),
                    ('banco_agrario', 'Banco Agrario'),
                    ('banco_gnb_sudameris', 'Banco GNB Sudameris'),
                ],
                'fintech': [
                    ('nequi', 'Nequi'),
                    ('daviplata', 'DaviPlata'),
                    ('movii', 'MOVii'),
                    ('dale', 'dale!'),
                    ('rappipay', 'RappiPay'),
                    ('tpaga', 'Tpaga'),
                    ('pse', 'PSE'),
                    ('efecty', 'Efecty'),
                    ('baloto', 'Baloto'),
                    ('gana', 'Gana'),
                ]
            },
            
            # COSTA RICA (CR)
            'CR': {
                'banks': [
                    ('banco_nacional_cr', 'Banco Nacional de Costa Rica'),
                    ('banco_costa_rica', 'Banco de Costa Rica'),
                    ('banco_popular_cr', 'Banco Popular'),
                    ('bac_san_jose', 'BAC San José'),
                    ('scotiabank_cr', 'Scotiabank Costa Rica'),
                    ('banco_promerica', 'Banco Promerica'),
                    ('banco_lafise', 'Banco LAFISE'),
                    ('davivienda_cr', 'Davivienda Costa Rica'),
                ],
                'fintech': [
                    ('sinpe_movil', 'SINPE Móvil'),
                    ('yappy_cr', 'Yappy'),
                    ('kushki_cr', 'Kushki'),
                ]
            },
            
            # DOMINICAN REPUBLIC (DO)
            'DO': {
                'banks': [
                    ('banco_popular_do', 'Banco Popular Dominicano'),
                    ('banco_reservas', 'Banreservas'),
                    ('banco_bhd', 'Banco BHD'),
                    ('scotiabank_do', 'Scotiabank República Dominicana'),
                    ('banco_santa_cruz', 'Banco Santa Cruz'),
                    ('banesco_do', 'Banesco República Dominicana'),
                    ('banco_vimenca', 'Banco Vimenca'),
                    ('banco_caribe', 'Banco Caribe'),
                ],
                'fintech': [
                    ('tpago_do', 'tPago'),
                    ('mi_pago', 'Mi Pago'),
                    ('paypal_do', 'PayPal'),
                    ('azul_pay', 'Azul Pay'),
                ]
            },
            
            # ECUADOR (EC)
            'EC': {
                'banks': [
                    ('banco_pichincha', 'Banco Pichincha'),
                    ('banco_pacifico', 'Banco del Pacífico'),
                    ('banco_guayaquil', 'Banco de Guayaquil'),
                    ('banco_produbanco', 'Produbanco'),
                    ('banco_bolivariano', 'Banco Bolivariano'),
                    ('banco_internacional', 'Banco Internacional'),
                    ('banco_austro', 'Banco del Austro'),
                    ('banco_machala', 'Banco de Machala'),
                ],
                'fintech': [
                    ('payphone', 'Payphone'),
                    ('kushki_ec', 'Kushki'),
                    ('paymentez', 'Paymentez'),
                    ('datafast', 'Datafast'),
                ]
            },
            
            # EL SALVADOR (SV)
            'SV': {
                'banks': [
                    ('banco_agricola', 'Banco Agrícola'),
                    ('banco_cuscatlan', 'Banco Cuscatlán'),
                    ('banco_america_central', 'Banco de América Central'),
                    ('banco_promerica_sv', 'Banco Promerica'),
                    ('banco_hipotecario', 'Banco Hipotecario'),
                    ('davivienda_sv', 'Davivienda El Salvador'),
                    ('scotiabank_sv', 'Scotiabank El Salvador'),
                ],
                'fintech': [
                    ('tigo_money_sv', 'Tigo Money'),
                    ('hugo', 'Hugo'),
                    ('chivo_wallet', 'Chivo Wallet'),
                ]
            },
            
            # GUATEMALA (GT)
            'GT': {
                'banks': [
                    ('banco_industrial', 'Banco Industrial'),
                    ('banrural', 'Banrural'),
                    ('banco_agromercantil', 'BAM - Banco Agromercantil'),
                    ('banco_promerica_gt', 'Banco Promerica'),
                    ('banco_ficohsa', 'Banco Ficohsa'),
                    ('banco_azteca_gt', 'Banco Azteca'),
                    ('banco_inmobiliario', 'Banco Inmobiliario'),
                ],
                'fintech': [
                    ('tigo_money_gt', 'Tigo Money'),
                    ('claro_pay', 'Claro Pay'),
                    ('visanet_gt', 'VisaNet Guatemala'),
                ]
            },
            
            # HONDURAS (HN)
            'HN': {
                'banks': [
                    ('banco_atlantida', 'Banco Atlántida'),
                    ('banco_ficohsa_hn', 'Banco Ficohsa'),
                    ('bac_honduras', 'BAC Honduras'),
                    ('banco_occidente_hn', 'Banco de Occidente'),
                    ('banpais', 'Banpaís'),
                    ('banco_azteca_hn', 'Banco Azteca'),
                    ('davivienda_hn', 'Davivienda Honduras'),
                ],
                'fintech': [
                    ('tigo_money_hn', 'Tigo Money'),
                    ('tengo', 'Tengo'),
                ]
            },
            
            # MEXICO (MX)
            'MX': {
                'banks': [
                    ('bbva_mexico', 'BBVA México'),
                    ('banamex', 'Citibanamex'),
                    ('santander_mexico', 'Santander México'),
                    ('banorte', 'Banorte'),
                    ('hsbc_mexico', 'HSBC México'),
                    ('scotiabank_mx', 'Scotiabank México'),
                    ('banco_azteca_mx', 'Banco Azteca'),
                    ('inbursa', 'Inbursa'),
                    ('banco_sabadell', 'Banco Sabadell'),
                    ('banregio', 'Banregio'),
                    ('banco_compartamos', 'Banco Compartamos'),
                ],
                'fintech': [
                    ('mercadopago_mx', 'Mercado Pago'),
                    ('clip', 'Clip'),
                    ('conekta', 'Conekta'),
                    ('openpay', 'Openpay'),
                    ('paypal_mx', 'PayPal'),
                    ('oxxo_pay', 'OXXO Pay'),
                    ('spei', 'SPEI'),
                    ('codi', 'CoDi'),
                    ('didi_pay', 'DiDi Pay'),
                    ('rappi_pay_mx', 'Rappi Pay'),
                    ('albo', 'albo'),
                    ('klar', 'Klar'),
                    ('fondeadora', 'Fondeadora'),
                ]
            },
            
            # NICARAGUA (NI)
            'NI': {
                'banks': [
                    ('banco_lafise_ni', 'Banco LAFISE'),
                    ('bac_nicaragua', 'BAC Nicaragua'),
                    ('banpro', 'Banpro'),
                    ('banco_ficohsa_ni', 'Banco Ficohsa Nicaragua'),
                    ('banco_avanz', 'Banco Avanz'),
                ],
                'fintech': [
                    ('banpro_movil', 'Banpro Móvil'),
                ]
            },
            
            # PANAMA (PA)
            'PA': {
                'banks': [
                    ('banco_general', 'Banco General'),
                    ('banistmo', 'Banistmo'),
                    ('bac_panama', 'BAC Panamá'),
                    ('banco_nacional_pa', 'Banco Nacional de Panamá'),
                    ('scotiabank_pa', 'Scotiabank Panamá'),
                    ('global_bank', 'Global Bank'),
                    ('banesco_pa', 'Banesco Panamá'),
                    ('multibank', 'Multibank'),
                    ('banco_delta', 'Banco Delta'),
                ],
                'fintech': [
                    ('yappy', 'Yappy'),
                    ('nequi_pa', 'Nequi Panamá'),
                    ('pago_facil', 'Pago Fácil'),
                ]
            },
            
            # PARAGUAY (PY)
            'PY': {
                'banks': [
                    ('banco_nacional_fomento', 'Banco Nacional de Fomento'),
                    ('banco_itau_py', 'Banco Itaú Paraguay'),
                    ('banco_continental', 'Banco Continental'),
                    ('banco_regional', 'Banco Regional'),
                    ('vision_banco', 'Visión Banco'),
                    ('banco_familiar', 'Banco Familiar'),
                    ('banco_gnb_py', 'Banco GNB Paraguay'),
                    ('bancop', 'Bancop'),
                ],
                'fintech': [
                    ('tigo_money_py', 'Tigo Money'),
                    ('billetera_personal', 'Billetera Personal'),
                    ('wally', 'Wally'),
                    ('zimple', 'Zimple'),
                ]
            },
            
            # PERU (PE)
            'PE': {
                'banks': [
                    ('bcp', 'Banco de Crédito del Perú (BCP)'),
                    ('bbva_peru', 'BBVA Perú'),
                    ('interbank', 'Interbank'),
                    ('scotiabank_pe', 'Scotiabank Perú'),
                    ('banco_nacion_pe', 'Banco de la Nación'),
                    ('mibanco', 'Mibanco'),
                    ('banco_pichincha_pe', 'Banco Pichincha Perú'),
                    ('banco_falabella_pe', 'Banco Falabella Perú'),
                    ('banco_ripley_pe', 'Banco Ripley Perú'),
                    ('banco_santander_pe', 'Banco Santander Perú'),
                ],
                'fintech': [
                    ('yape', 'Yape'),
                    ('plin', 'Plin'),
                    ('tunki', 'Tunki'),
                    ('agora_pay', 'Agora Pay'),
                    ('mercadopago_pe', 'Mercado Pago'),
                    ('paypal_pe', 'PayPal'),
                    ('niubiz', 'Niubiz'),
                    ('pagoefectivo', 'PagoEfectivo'),
                    ('lukita', 'Lukita'),
                ]
            },
            
            # PUERTO RICO (PR)
            'PR': {
                'banks': [
                    ('banco_popular_pr', 'Banco Popular de Puerto Rico'),
                    ('oriental_bank', 'Oriental Bank'),
                    ('firstbank_pr', 'FirstBank Puerto Rico'),
                    ('banco_santander_pr', 'Banco Santander Puerto Rico'),
                ],
                'fintech': [
                    ('ath_movil', 'ATH Móvil'),
                    ('paypal_pr', 'PayPal'),
                ]
            },
            
            # SPAIN (ES)
            'ES': {
                'banks': [
                    ('santander_es', 'Banco Santander'),
                    ('bbva_es', 'BBVA'),
                    ('caixabank', 'CaixaBank'),
                    ('banco_sabadell_es', 'Banco Sabadell'),
                    ('bankia', 'Bankia'),
                    ('bankinter', 'Bankinter'),
                    ('unicaja', 'Unicaja Banco'),
                    ('kutxabank', 'Kutxabank'),
                    ('banco_mediolanum', 'Banco Mediolanum'),
                    ('ing_es', 'ING España'),
                    ('deutsche_bank_es', 'Deutsche Bank España'),
                ],
                'fintech': [
                    ('bizum', 'Bizum'),
                    ('paypal_es', 'PayPal'),
                    ('revolut_es', 'Revolut'),
                    ('n26_es', 'N26'),
                    ('wise_es', 'Wise'),
                    ('bnext', 'Bnext'),
                    ('verse', 'Verse'),
                    ('twyp', 'Twyp'),
                ]
            },
            
            # UNITED STATES (US)
            'US': {
                'banks': [
                    ('chase', 'Chase Bank'),
                    ('bank_of_america', 'Bank of America'),
                    ('wells_fargo', 'Wells Fargo'),
                    ('citibank_us', 'Citibank'),
                    ('us_bank', 'U.S. Bank'),
                    ('pnc_bank', 'PNC Bank'),
                    ('truist', 'Truist Bank'),
                    ('td_bank', 'TD Bank'),
                    ('capital_one', 'Capital One'),
                    ('fifth_third', 'Fifth Third Bank'),
                    ('regions_bank', 'Regions Bank'),
                    ('ally_bank', 'Ally Bank'),
                ],
                'fintech': [
                    ('zelle', 'Zelle'),
                    ('venmo', 'Venmo'),
                    ('cash_app', 'Cash App'),
                    ('paypal_us', 'PayPal'),
                    ('apple_pay', 'Apple Pay'),
                    ('google_pay', 'Google Pay'),
                    ('wise_us', 'Wise'),
                    ('chime', 'Chime'),
                    ('current', 'Current'),
                    ('varo', 'Varo'),
                    ('sofi', 'SoFi'),
                ]
            },
            
            # URUGUAY (UY)
            'UY': {
                'banks': [
                    ('banco_republica', 'Banco República (BROU)'),
                    ('banco_santander_uy', 'Banco Santander Uruguay'),
                    ('banco_itau_uy', 'Banco Itaú Uruguay'),
                    ('scotiabank_uy', 'Scotiabank Uruguay'),
                    ('banco_hsbc_uy', 'HSBC Uruguay'),
                    ('banco_bbva_uy', 'BBVA Uruguay'),
                    ('banco_heritage', 'Banco Heritage'),
                    ('banco_bandes', 'Banco Bandes Uruguay'),
                ],
                'fintech': [
                    ('mercadopago_uy', 'Mercado Pago'),
                    ('paganza', 'Paganza'),
                    ('redpagos', 'RedPagos'),
                    ('prex', 'Prex'),
                    ('midinero', 'MiDinero'),
                ]
            },
            
            # VENEZUELA (VE)
            'VE': {
                'banks': [
                    ('banco_venezuela', 'Banco de Venezuela'),
                    ('banesco', 'Banesco'),
                    ('banco_mercantil', 'Banco Mercantil'),
                    ('banco_provincial', 'Banco Provincial'),
                    ('banco_bicentenario', 'Banco Bicentenario'),
                    ('banco_exterior', 'Banco Exterior'),
                    ('banco_caroni', 'Banco Caroní'),
                    ('banco_nacional_credito', 'Banco Nacional de Crédito (BNC)'),
                    ('banco_plaza', 'Banco Plaza'),
                    ('banco_activo', 'Banco Activo'),
                    ('banco_tesoro', 'Banco del Tesoro'),
                    ('banco_agricola_vzla', 'Banco Agrícola de Venezuela'),
                    ('banco_fondo_comun', 'Banco Fondo Común (BFC)'),
                    ('bancamiga', 'Bancamiga'),
                    ('banco_sofitasa', 'Banco Sofitasa'),
                    ('banplus', 'Banplus'),
                    ('banco_100', '100% Banco'),
                ],
                'fintech': [
                    ('pago_movil', 'Pago Móvil'),
                    ('biopago', 'BioPago'),
                    ('reserve', 'Reserve'),
                    ('zinli', 'Zinli'),
                    ('pipol_pay', 'Pipol Pay'),
                    ('wally', 'Wally'),
                ]
            },
            
            # PORTUGAL (PT)
            'PT': {
                'banks': [
                    ('caixa_geral', 'Caixa Geral de Depósitos'),
                    ('millennium_bcp', 'Millennium BCP'),
                    ('novo_banco', 'Novo Banco'),
                    ('santander_pt', 'Santander Totta'),
                    ('bpi', 'BPI'),
                    ('credito_agricola', 'Crédito Agrícola'),
                    ('montepio', 'Montepio'),
                    ('bankinter_pt', 'Bankinter Portugal'),
                ],
                'fintech': [
                    ('mb_way', 'MB WAY'),
                    ('revolut_pt', 'Revolut'),
                    ('paypal_pt', 'PayPal'),
                    ('wise_pt', 'Wise'),
                    ('moey', 'Moey!'),
                ]
            },
            
            # NIGERIA (NG) - Major stablecoin adoption
            'NG': {
                'banks': [
                    ('gtbank', 'GTBank'),
                    ('first_bank', 'First Bank of Nigeria'),
                    ('access_bank', 'Access Bank'),
                    ('zenith_bank', 'Zenith Bank'),
                    ('uba', 'United Bank for Africa (UBA)'),
                    ('union_bank_ng', 'Union Bank'),
                    ('fidelity_bank', 'Fidelity Bank'),
                    ('sterling_bank', 'Sterling Bank'),
                    ('stanbic_ibtc', 'Stanbic IBTC'),
                    ('ecobank_ng', 'Ecobank Nigeria'),
                ],
                'fintech': [
                    ('opay', 'OPay'),
                    ('palmpay', 'PalmPay'),
                    ('kuda', 'Kuda'),
                    ('paystack', 'Paystack'),
                    ('flutterwave', 'Flutterwave'),
                    ('paga', 'Paga'),
                    ('carbon', 'Carbon'),
                    ('chipper_cash', 'Chipper Cash'),
                    ('bundle', 'Bundle'),
                    ('bitnob', 'Bitnob'),
                ]
            },
            
            # KENYA (KE)
            'KE': {
                'banks': [
                    ('equity_bank', 'Equity Bank'),
                    ('kcb', 'Kenya Commercial Bank (KCB)'),
                    ('cooperative_bank', 'Co-operative Bank'),
                    ('absa_kenya', 'Absa Bank Kenya'),
                    ('stanchart_ke', 'Standard Chartered Kenya'),
                    ('dtb_kenya', 'Diamond Trust Bank'),
                    ('ncba', 'NCBA Bank'),
                ],
                'fintech': [
                    ('mpesa', 'M-Pesa'),
                    ('airtel_money_ke', 'Airtel Money'),
                    ('tkash', 'T-Kash'),
                    ('pesalink', 'PesaLink'),
                    ('chipper_cash_ke', 'Chipper Cash'),
                ]
            },
            
            # SOUTH AFRICA (ZA)
            'ZA': {
                'banks': [
                    ('fnb', 'First National Bank (FNB)'),
                    ('standard_bank', 'Standard Bank'),
                    ('absa', 'Absa'),
                    ('nedbank', 'Nedbank'),
                    ('capitec', 'Capitec Bank'),
                    ('investec', 'Investec'),
                    ('discovery_bank', 'Discovery Bank'),
                    ('tyme_bank', 'TymeBank'),
                ],
                'fintech': [
                    ('payfast', 'PayFast'),
                    ('ozow', 'Ozow'),
                    ('snapscan', 'SnapscanScan'),
                    ('zapper', 'Zapper'),
                    ('payflex', 'Payflex'),
                    ('luno', 'Luno'),
                    ('valr', 'VALR'),
                ]
            },
            
            # GHANA (GH)
            'GH': {
                'banks': [
                    ('gcb_bank', 'GCB Bank'),
                    ('ecobank_gh', 'Ecobank Ghana'),
                    ('stanbic_gh', 'Stanbic Bank Ghana'),
                    ('absa_ghana', 'Absa Bank Ghana'),
                    ('calbank', 'CalBank'),
                    ('fidelity_gh', 'Fidelity Bank Ghana'),
                    ('zenith_gh', 'Zenith Bank Ghana'),
                ],
                'fintech': [
                    ('mtn_momo', 'MTN Mobile Money'),
                    ('vodafone_cash', 'Vodafone Cash'),
                    ('airteltigo_money', 'AirtelTigo Money'),
                    ('zeepay', 'Zeepay'),
                    ('expresspay', 'ExpressPay'),
                ]
            },
            
            # PHILIPPINES (PH)
            'PH': {
                'banks': [
                    ('bdo', 'BDO Unibank'),
                    ('bpi', 'Bank of the Philippine Islands (BPI)'),
                    ('metrobank', 'Metrobank'),
                    ('landbank', 'Land Bank of the Philippines'),
                    ('pnb_ph', 'Philippine National Bank'),
                    ('security_bank_ph', 'Security Bank'),
                    ('unionbank_ph', 'UnionBank'),
                    ('chinabank', 'China Bank'),
                ],
                'fintech': [
                    ('gcash', 'GCash'),
                    ('paymaya', 'PayMaya'),
                    ('coins_ph', 'Coins.ph'),
                    ('grabpay_ph', 'GrabPay'),
                    ('dragonpay', 'DragonPay'),
                    ('paypal_ph', 'PayPal'),
                    ('instapay', 'InstaPay'),
                    ('pesonet', 'PesoNet'),
                ]
            },
            
            # INDIA (IN)
            'IN': {
                'banks': [
                    ('sbi', 'State Bank of India'),
                    ('hdfc_bank', 'HDFC Bank'),
                    ('icici_bank', 'ICICI Bank'),
                    ('axis_bank', 'Axis Bank'),
                    ('kotak_mahindra', 'Kotak Mahindra Bank'),
                    ('pnb_india', 'Punjab National Bank'),
                    ('bank_of_baroda', 'Bank of Baroda'),
                    ('canara_bank', 'Canara Bank'),
                    ('idbi_bank', 'IDBI Bank'),
                    ('yes_bank', 'Yes Bank'),
                ],
                'fintech': [
                    ('upi', 'UPI'),
                    ('paytm', 'Paytm'),
                    ('google_pay_in', 'Google Pay'),
                    ('phonepe', 'PhonePe'),
                    ('amazon_pay_in', 'Amazon Pay'),
                    ('mobikwik', 'MobiKwik'),
                    ('freecharge', 'Freecharge'),
                    ('bhim', 'BHIM'),
                    ('razorpay', 'Razorpay'),
                ]
            },
            
            # INDONESIA (ID)
            'ID': {
                'banks': [
                    ('bank_mandiri', 'Bank Mandiri'),
                    ('bca', 'Bank Central Asia (BCA)'),
                    ('bni', 'Bank Negara Indonesia (BNI)'),
                    ('bri', 'Bank Rakyat Indonesia (BRI)'),
                    ('cimb_niaga', 'CIMB Niaga'),
                    ('danamon', 'Bank Danamon'),
                    ('permata_bank', 'PermataBank'),
                    ('btpn', 'Bank BTPN'),
                ],
                'fintech': [
                    ('gopay', 'GoPay'),
                    ('ovo', 'OVO'),
                    ('dana', 'DANA'),
                    ('linkaja', 'LinkAja'),
                    ('shopeepay_id', 'ShopeePay'),
                    ('jenius', 'Jenius'),
                    ('sakuku', 'Sakuku'),
                    ('doku', 'DOKU'),
                ]
            },
            
            # VIETNAM (VN)
            'VN': {
                'banks': [
                    ('vietcombank', 'Vietcombank'),
                    ('vietinbank', 'VietinBank'),
                    ('bidv', 'BIDV'),
                    ('agribank', 'Agribank'),
                    ('techcombank', 'Techcombank'),
                    ('mbbank', 'MB Bank'),
                    ('vpbank', 'VPBank'),
                    ('acb', 'Asia Commercial Bank (ACB)'),
                    ('sacombank', 'Sacombank'),
                ],
                'fintech': [
                    ('momo_vn', 'MoMo'),
                    ('zalopay', 'ZaloPay'),
                    ('viettelpay', 'ViettelPay'),
                    ('vnpay', 'VNPAY'),
                    ('shopeepay_vn', 'ShopeePay'),
                    ('grabpay_vn', 'GrabPay'),
                ]
            },
            
            # THAILAND (TH)
            'TH': {
                'banks': [
                    ('bangkok_bank', 'Bangkok Bank'),
                    ('kbank', 'Kasikornbank (KBank)'),
                    ('scb', 'Siam Commercial Bank (SCB)'),
                    ('krungsri', 'Bank of Ayudhya (Krungsri)'),
                    ('ktb', 'Krungthai Bank (KTB)'),
                    ('tmb', 'TMB Bank'),
                    ('cimb_thai', 'CIMB Thai'),
                    ('uob_thai', 'United Overseas Bank (UOB)'),
                ],
                'fintech': [
                    ('promptpay', 'PromptPay'),
                    ('truemoney', 'TrueMoney'),
                    ('rabbit_line_pay', 'Rabbit LINE Pay'),
                    ('shopeepay_th', 'ShopeePay'),
                    ('airpay', 'AirPay'),
                    ('bluepay', 'BluePay'),
                ]
            },
            
            # TURKEY (TR)
            'TR': {
                'banks': [
                    ('ziraat_bankasi', 'Ziraat Bankası'),
                    ('is_bankasi', 'Türkiye İş Bankası'),
                    ('garanti_bbva', 'Garanti BBVA'),
                    ('akbank', 'Akbank'),
                    ('yapi_kredi', 'Yapı Kredi'),
                    ('halkbank', 'Halkbank'),
                    ('vakifbank', 'VakıfBank'),
                    ('denizbank', 'DenizBank'),
                    ('qnb_finansbank', 'QNB Finansbank'),
                ],
                'fintech': [
                    ('papara', 'Papara'),
                    ('tosla', 'Tosla'),
                    ('ininal', 'ininal'),
                    ('paycell', 'Paycell'),
                    ('bkm_express', 'BKM Express'),
                    ('param', 'Param'),
                    ('iyzico', 'iyzico'),
                ]
            },
            
            # UAE (AE)
            'AE': {
                'banks': [
                    ('emirates_nbd', 'Emirates NBD'),
                    ('adcb', 'Abu Dhabi Commercial Bank'),
                    ('fab', 'First Abu Dhabi Bank'),
                    ('dib', 'Dubai Islamic Bank'),
                    ('adib', 'Abu Dhabi Islamic Bank'),
                    ('cbd', 'Commercial Bank of Dubai'),
                    ('rakbank', 'RAKBANK'),
                    ('mashreq', 'Mashreq Bank'),
                    ('hsbc_uae', 'HSBC UAE'),
                ],
                'fintech': [
                    ('payit', 'Payit'),
                    ('beam', 'Beam Wallet'),
                    ('samsung_pay_ae', 'Samsung Pay'),
                    ('apple_pay_ae', 'Apple Pay'),
                    ('google_pay_ae', 'Google Pay'),
                    ('careem_pay', 'Careem Pay'),
                    ('etisalat_wallet', 'Etisalat Wallet'),
                    ('botim', 'BOTIM'),
                ]
            },
            
            # UKRAINE (UA)
            'UA': {
                'banks': [
                    ('privatbank', 'PrivatBank'),
                    ('monobank', 'Monobank'),
                    ('oschadbank', 'Oschadbank'),
                    ('ukreximbank', 'Ukreximbank'),
                    ('raiffeisen_ua', 'Raiffeisen Bank Ukraine'),
                    ('ukrsibbank', 'UkrSibbank'),
                    ('otp_bank_ua', 'OTP Bank Ukraine'),
                    ('pumb', 'PUMB'),
                ],
                'fintech': [
                    ('portmone', 'Portmone'),
                    ('easypay', 'EasyPay'),
                    ('privat24', 'Privat24'),
                    ('google_pay_ua', 'Google Pay'),
                    ('apple_pay_ua', 'Apple Pay'),
                    ('novanapay', 'NovaPay'),
                ]
            },
            
            # POLAND (PL)
            'PL': {
                'banks': [
                    ('pko_bp', 'PKO Bank Polski'),
                    ('pekao', 'Bank Pekao'),
                    ('mbank_pl', 'mBank'),
                    ('ing_pl', 'ING Bank Śląski'),
                    ('santander_pl', 'Santander Bank Polska'),
                    ('bnp_paribas_pl', 'BNP Paribas Poland'),
                    ('millennium', 'Bank Millennium'),
                    ('alior_bank', 'Alior Bank'),
                ],
                'fintech': [
                    ('blik', 'BLIK'),
                    ('przelewy24', 'Przelewy24'),
                    ('payu_pl', 'PayU'),
                    ('revolut_pl', 'Revolut'),
                    ('paypal_pl', 'PayPal'),
                    ('google_pay_pl', 'Google Pay'),
                    ('apple_pay_pl', 'Apple Pay'),
                ]
            }
        }
        
        created_count = 0
        updated_count = 0
        
        with transaction.atomic():
            for country_code, methods in payment_methods_data.items():
                try:
                    country = Country.objects.get(code=country_code)
                    self.stdout.write(f'\nProcessing {country.name} ({country_code})...')
                    
                    # Process banks
                    for name, display_name in methods.get('banks', []):
                        # Check if bank exists
                        bank = Bank.objects.filter(
                            name=display_name,
                            country=country
                        ).first()
                        
                        if not bank:
                            # Create bank if it doesn't exist
                            bank = Bank.objects.create(
                                code=name.upper(),
                                name=display_name,
                                short_name=display_name.split()[0],  # First word as short name
                                country=country,
                                supports_checking=True,
                                supports_savings=True,
                                is_active=True
                            )
                            self.stdout.write(f'  Created bank: {display_name}')
                        
                        # Create or update payment method
                        payment_method, created = P2PPaymentMethod.objects.get_or_create(
                            name=name,
                            defaults={
                                'display_name': display_name,
                                'provider_type': 'bank',
                                'is_active': True,
                                'icon': 'building-2',
                                'country_code': country_code,
                                'bank': bank,
                                'country': country,
                                'requires_account_number': True,
                                'requires_phone': False,
                                'requires_email': False,
                                'description': f'{display_name} - {country.name}'
                            }
                        )
                        
                        if created:
                            created_count += 1
                            self.stdout.write(f'  Created payment method: {display_name}')
                        else:
                            # Update existing payment method
                            payment_method.display_name = display_name
                            payment_method.bank = bank
                            payment_method.country = country
                            payment_method.save()
                            updated_count += 1
                            self.stdout.write(f'  Updated payment method: {display_name}')
                    
                    # Process fintech
                    for name, display_name in methods.get('fintech', []):
                        # Determine requirements based on common patterns
                        requires_phone = any(keyword in name.lower() for keyword in ['movil', 'money', 'yappy', 'nequi', 'plin', 'yape'])
                        requires_email = any(keyword in name.lower() for keyword in ['paypal', 'wise', 'zelle'])
                        requires_account = not requires_phone and not requires_email
                        
                        # Determine icon based on type
                        if 'pago' in name.lower() or 'pay' in name.lower():
                            icon = 'credit-card'
                        elif requires_phone:
                            icon = 'smartphone'
                        elif 'wallet' in name.lower() or 'billetera' in name.lower():
                            icon = 'wallet'
                        else:
                            icon = 'trending-up'
                        
                        # Create or update payment method
                        payment_method, created = P2PPaymentMethod.objects.get_or_create(
                            name=name,
                            defaults={
                                'display_name': display_name,
                                'provider_type': 'fintech',
                                'is_active': True,
                                'icon': icon,
                                'country_code': country_code,
                                'country': country,
                                'requires_account_number': requires_account,
                                'requires_phone': requires_phone,
                                'requires_email': requires_email,
                                'description': f'{display_name} - Digital Wallet - {country.name}'
                            }
                        )
                        
                        if created:
                            created_count += 1
                            self.stdout.write(f'  Created fintech: {display_name}')
                        else:
                            # Update existing payment method
                            payment_method.display_name = display_name
                            payment_method.country = country
                            payment_method.icon = icon
                            payment_method.requires_phone = requires_phone
                            payment_method.requires_email = requires_email
                            payment_method.requires_account_number = requires_account
                            payment_method.save()
                            updated_count += 1
                            self.stdout.write(f'  Updated fintech: {display_name}')
                
                except Country.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f'Country {country_code} not found in database'))
        
        self.stdout.write(self.style.SUCCESS(
            f'\nSuccessfully populated payment methods: {created_count} created, {updated_count} updated'
        ))
        
        # Show summary
        total_methods = P2PPaymentMethod.objects.filter(is_active=True).count()
        self.stdout.write(f'\nTotal active payment methods in database: {total_methods}')
        
        # Show breakdown by country
        self.stdout.write('\nPayment methods by country:')
        for country_code in sorted(payment_methods_data.keys()):
            count = P2PPaymentMethod.objects.filter(country_code=country_code, is_active=True).count()
            try:
                country_name = Country.objects.get(code=country_code).name
                self.stdout.write(f'  {country_name} ({country_code}): {count} methods')
            except Country.DoesNotExist:
                self.stdout.write(f'  {country_code}: {count} methods (country not in DB)')
