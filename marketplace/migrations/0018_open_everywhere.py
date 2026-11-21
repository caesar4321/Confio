"""Comprar opens in every country and city (2026-11-21, self-serve).

Cities with no row already sell (checkout.area_is_live); these rows exist so
the app's city picker and GPS matching (which only know rows) reach every
country without a release. New rows are live; the 25 cities seeded in 0002
are not touched here (prod flips them as a recorded data change).

Each line: ISO-2 | city | latitude | longitude | radius km. Names follow
what Comprar's Spanish-speaking users call them. Coordinates are city centres
for matching a phone's position; nearest centre wins where radii overlap.
"""
from decimal import Decimal

from django.db import migrations, models

CITIES = """
AR|Bahía Blanca|-38.7183|-62.2663|15
AR|Corrientes|-27.4692|-58.8306|12
AR|Posadas|-27.3671|-55.8961|10
AR|San Juan|-31.5375|-68.5364|15
AR|Resistencia|-27.4606|-58.9839|12
AR|Santiago del Estero|-27.7951|-64.2615|12
AR|San Salvador de Jujuy|-24.1858|-65.2995|12
AR|Paraná|-31.7319|-60.5238|12
AR|Comodoro Rivadavia|-45.8641|-67.4966|12
AR|San Carlos de Bariloche|-41.1335|-71.3103|12
AR|Ushuaia|-54.8019|-68.3030|10
BO|Sucre|-19.0196|-65.2619|20
BO|Oruro|-17.9833|-67.1500|15
BO|Potosí|-19.5836|-65.7531|15
BO|Tarija|-21.5355|-64.7296|15
BO|Trinidad|-14.8333|-64.9000|15
BO|Cobija|-11.0267|-68.7692|10
BO|Montero|-17.3422|-63.2558|10
BO|Riberalta|-11.0068|-66.0617|10
BO|Yacuiba|-22.0153|-63.6775|10
VE|Puerto La Cruz|10.2131|-64.6328|10
VE|Ciudad Bolívar|8.1222|-63.5497|20
VE|Barinas|8.6226|-70.2075|20
VE|Coro|11.4045|-69.6734|15
VE|Los Teques|10.3442|-67.0433|10
VE|Guarenas|10.4667|-66.6167|10
VE|Acarigua|9.5545|-69.1956|15
VE|Guanare|9.0418|-69.7421|15
VE|San Fernando de Apure|7.8878|-67.4724|15
VE|Valera|9.3178|-70.6036|15
VE|Porlamar|10.9577|-63.8697|20
VE|Cabimas|10.4019|-71.4461|15
VE|Punto Fijo|11.6956|-70.1997|15
VE|San Juan de los Morros|9.9119|-67.3540|10
VE|Tucupita|9.0622|-62.0510|10
VE|Puerto Ayacucho|5.6639|-67.6236|10
VE|Carora|10.1717|-70.0806|10
VE|El Tigre|8.8875|-64.2453|15
BR|São Paulo|-23.5505|-46.6333|50
BR|Rio de Janeiro|-22.9068|-43.1729|40
BR|Brasília|-15.7939|-47.8828|35
BR|Salvador|-12.9777|-38.5016|30
BR|Fortaleza|-3.7319|-38.5267|30
BR|Belo Horizonte|-19.9167|-43.9345|30
BR|Manaus|-3.1190|-60.0217|30
BR|Curitiba|-25.4284|-49.2733|30
BR|Recife|-8.0476|-34.8770|30
BR|Porto Alegre|-30.0346|-51.2177|30
BR|Belém|-1.4558|-48.4902|25
BR|Goiânia|-16.6869|-49.2648|25
BR|Campinas|-22.9099|-47.0626|20
BR|Florianópolis|-27.5954|-48.5480|20
BR|Natal|-5.7945|-35.2110|20
BR|São Luís|-2.5307|-44.3068|20
BR|Boa Vista|2.8235|-60.6758|15
BR|Pacaraima|4.4796|-61.1478|10
BR|Corumbá|-19.0089|-57.6517|10
BR|Foz do Iguaçu|-25.5163|-54.5854|10
CL|Santiago|-33.4489|-70.6693|40
CL|Valparaíso|-33.0472|-71.6127|10
CL|Viña del Mar|-33.0245|-71.5518|10
CL|Concepción|-36.8270|-73.0503|20
CL|Antofagasta|-23.6509|-70.3975|20
CL|La Serena|-29.9027|-71.2519|15
CL|Temuco|-38.7359|-72.5904|15
CL|Iquique|-20.2307|-70.1357|15
CL|Arica|-18.4783|-70.3126|15
CL|Calama|-22.4544|-68.9294|15
CL|Rancagua|-34.1708|-70.7444|15
CL|Talca|-35.4264|-71.6554|15
CL|Puerto Montt|-41.4693|-72.9424|15
CL|Punta Arenas|-53.1638|-70.9171|15
CL|Copiapó|-27.3668|-70.3323|15
CO|Bogotá|4.7110|-74.0721|35
CO|Medellín|6.2442|-75.5812|25
CO|Cali|3.4516|-76.5320|25
CO|Barranquilla|10.9685|-74.7813|20
CO|Cartagena|10.3910|-75.4794|20
CO|Cúcuta|7.8939|-72.5078|20
CO|Bucaramanga|7.1193|-73.1227|20
CO|Pereira|4.8133|-75.6961|15
CO|Santa Marta|11.2408|-74.1990|15
CO|Ibagué|4.4389|-75.2322|15
CO|Manizales|5.0703|-75.5138|15
CO|Villavicencio|4.1420|-73.6266|15
CO|Pasto|1.2136|-77.2811|15
CO|Montería|8.7479|-75.8814|15
CO|Neiva|2.9273|-75.2819|15
CO|Armenia|4.5339|-75.6811|15
CO|Valledupar|10.4631|-73.2532|15
CO|Riohacha|11.5444|-72.9072|10
CO|Popayán|2.4448|-76.6147|15
CO|Sincelejo|9.3047|-75.3978|10
CR|San José|9.9281|-84.0907|20
CR|Alajuela|10.0163|-84.2116|10
CR|Cartago|9.8644|-83.9194|10
CR|Heredia|9.9986|-84.1165|8
CR|Liberia|10.6346|-85.4407|10
CR|Limón|9.9907|-83.0359|10
CR|Puntarenas|9.9763|-84.8384|10
CU|La Habana|23.1136|-82.3666|25
CU|Santiago de Cuba|20.0247|-75.8219|15
CU|Camagüey|21.3808|-77.9170|15
CU|Holguín|20.8872|-76.2630|15
CU|Santa Clara|22.4069|-79.9647|15
DO|Santo Domingo|18.4861|-69.9312|25
DO|Santiago de los Caballeros|19.4517|-70.6970|15
DO|La Romana|18.4273|-68.9728|10
DO|Punta Cana|18.5601|-68.3725|15
DO|San Pedro de Macorís|18.4539|-69.3086|10
DO|Puerto Plata|19.7808|-70.6871|10
EC|Quito|-0.1807|-78.4678|25
EC|Guayaquil|-2.1709|-79.9224|25
EC|Cuenca|-2.9001|-79.0059|15
EC|Santo Domingo|-0.2530|-79.1754|10
EC|Ambato|-1.2491|-78.6168|15
EC|Manta|-0.9677|-80.7089|15
EC|Portoviejo|-1.0546|-80.4545|10
EC|Machala|-3.2581|-79.9554|10
EC|Loja|-3.9931|-79.2042|10
EC|Riobamba|-1.6636|-78.6546|10
EC|Ibarra|0.3517|-78.1223|10
EC|Esmeraldas|0.9682|-79.6517|10
SV|San Salvador|13.6929|-89.2182|20
SV|Santa Ana|13.9946|-89.5598|10
SV|San Miguel|13.4833|-88.1833|10
GT|Ciudad de Guatemala|14.6349|-90.5069|25
GT|Quetzaltenango|14.8347|-91.5181|10
GT|Escuintla|14.3050|-90.7850|10
GT|Antigua Guatemala|14.5586|-90.7295|8
GT|Cobán|15.4708|-90.3708|10
GT|Puerto Barrios|15.7278|-88.5944|10
HN|Tegucigalpa|14.0723|-87.1921|20
HN|San Pedro Sula|15.5042|-88.0250|20
HN|La Ceiba|15.7597|-86.7822|10
HN|Choluteca|13.3007|-87.1908|10
HN|Comayagua|14.4513|-87.6375|10
MX|Ciudad de México|19.4326|-99.1332|40
MX|Guadalajara|20.6597|-103.3496|30
MX|Monterrey|25.6866|-100.3161|30
MX|Puebla|19.0414|-98.2063|20
MX|Tijuana|32.5149|-117.0382|15
MX|León|21.1221|-101.6824|20
MX|Ciudad Juárez|31.6904|-106.4245|15
MX|Mérida|20.9674|-89.5926|20
MX|Cancún|21.1619|-86.8515|20
MX|Querétaro|20.5888|-100.3899|20
MX|San Luis Potosí|22.1565|-100.9855|15
MX|Aguascalientes|21.8853|-102.2916|15
MX|Hermosillo|29.0729|-110.9559|15
MX|Chihuahua|28.6353|-106.0889|15
MX|Mexicali|32.6245|-115.4523|15
MX|Culiacán|24.8091|-107.3940|15
MX|Toluca|19.2826|-99.6557|15
MX|Morelia|19.7060|-101.1949|15
MX|Veracruz|19.1738|-96.1342|15
MX|Acapulco|16.8531|-99.8237|15
MX|Oaxaca|17.0732|-96.7266|10
MX|Tuxtla Gutiérrez|16.7528|-93.1152|10
MX|Villahermosa|17.9892|-92.9475|10
MX|Saltillo|25.4232|-101.0053|15
MX|Torreón|25.5428|-103.4068|15
MX|Durango|24.0277|-104.6532|10
MX|Mazatlán|23.2494|-106.4111|10
MX|Tampico|22.2331|-97.8611|10
MX|Reynosa|26.0508|-98.2979|10
MX|Matamoros|25.8690|-97.5027|10
MX|Nuevo Laredo|27.4779|-99.5496|10
MX|Cuernavaca|18.9242|-99.2216|10
MX|Xalapa|19.5438|-96.9102|10
MX|Playa del Carmen|20.6296|-87.0739|10
MX|Tapachula|14.9056|-92.2633|10
MX|La Paz|24.1426|-110.3128|10
NI|Managua|12.1364|-86.2514|20
NI|León|12.4379|-86.8780|10
NI|Masaya|11.9744|-86.0942|8
NI|Granada|11.9344|-85.9560|8
NI|Estelí|13.0919|-86.3538|8
NI|Chinandega|12.6294|-87.1311|8
PA|Ciudad de Panamá|8.9824|-79.5199|25
PA|Colón|9.3592|-79.9014|10
PA|David|8.4273|-82.4309|10
PA|Santiago de Veraguas|8.1000|-80.9833|8
PA|La Chorrera|8.8803|-79.7833|10
PY|Asunción|-25.2637|-57.5759|20
PY|Ciudad del Este|-25.5097|-54.6111|10
PY|Encarnación|-27.3306|-55.8667|10
PY|Pedro Juan Caballero|-22.5472|-55.7333|10
PY|Coronel Oviedo|-25.4167|-56.4500|8
PY|Concepción|-23.4064|-57.4344|8
PE|Lima|-12.0464|-77.0428|40
PE|Arequipa|-16.4090|-71.5375|20
PE|Trujillo|-8.1116|-79.0288|20
PE|Chiclayo|-6.7714|-79.8409|15
PE|Piura|-5.1945|-80.6328|15
PE|Cusco|-13.5320|-71.9675|15
PE|Iquitos|-3.7437|-73.2516|15
PE|Huancayo|-12.0651|-75.2049|15
PE|Tacna|-18.0066|-70.2463|15
PE|Pucallpa|-8.3791|-74.5539|10
PE|Chimbote|-9.0853|-78.5783|10
PE|Ica|-14.0678|-75.7286|10
PE|Juliaca|-15.5000|-70.1333|10
PE|Puno|-15.8402|-70.0219|10
PE|Cajamarca|-7.1638|-78.5003|10
PE|Ayacucho|-13.1588|-74.2239|10
PE|Tumbes|-3.5669|-80.4515|10
PE|Huánuco|-9.9306|-76.2422|10
PR|San Juan|18.4655|-66.1057|20
PR|Ponce|18.0111|-66.6141|10
PR|Mayagüez|18.2013|-67.1397|10
PR|Caguas|18.2341|-66.0485|10
PR|Arecibo|18.4724|-66.7157|10
UY|Montevideo|-34.9011|-56.1645|25
UY|Salto|-31.3833|-57.9667|10
UY|Paysandú|-32.3214|-58.0756|10
UY|Maldonado|-34.9000|-54.9500|10
UY|Rivera|-30.9053|-55.5508|10
UY|Colonia del Sacramento|-34.4626|-57.8398|8
UY|Tacuarembó|-31.7111|-55.9811|8
ES|Madrid|40.4168|-3.7038|30
ES|Barcelona|41.3874|2.1686|25
ES|Valencia|39.4699|-0.3763|20
ES|Sevilla|37.3891|-5.9845|20
ES|Zaragoza|41.6488|-0.8891|15
ES|Málaga|36.7213|-4.4214|15
ES|Murcia|37.9922|-1.1307|15
ES|Palma|39.5696|2.6502|15
ES|Las Palmas de Gran Canaria|28.1235|-15.4363|15
ES|Santa Cruz de Tenerife|28.4636|-16.2518|15
ES|Bilbao|43.2630|-2.9350|15
ES|Alicante|38.3452|-0.4810|15
ES|Valladolid|41.6523|-4.7245|10
ES|Vigo|42.2406|-8.7207|10
ES|A Coruña|43.3623|-8.4115|10
ES|Granada|37.1773|-3.5986|10
US|Miami|25.7617|-80.1918|30
US|Nueva York|40.7128|-74.0060|35
US|Houston|29.7604|-95.3698|35
US|Los Ángeles|34.0522|-118.2437|40
US|Orlando|28.5383|-81.3792|25
US|Chicago|41.8781|-87.6298|30
US|Dallas|32.7767|-96.7970|30
US|Washington|38.9072|-77.0369|25
US|Atlanta|33.7490|-84.3880|25
US|San Antonio|29.4241|-98.4936|25
US|Phoenix|33.4484|-112.0740|30
US|San Francisco|37.7749|-122.4194|25
US|Boston|42.3601|-71.0589|20
US|Tampa|27.9506|-82.4572|20
US|Las Vegas|36.1699|-115.1398|20
US|Denver|39.7392|-104.9903|20
US|Seattle|47.6062|-122.3321|20
US|Austin|30.2672|-97.7431|20
US|San Diego|32.7157|-117.1611|15
US|Filadelfia|39.9526|-75.1652|20
US|Charlotte|35.2271|-80.8431|20
US|Salt Lake City|40.7608|-111.8910|15
US|El Paso|31.7619|-106.4850|15
CA|Toronto|43.6532|-79.3832|30
CA|Montreal|45.5017|-73.5673|25
CA|Vancouver|49.2827|-123.1207|25
CA|Ottawa|45.4215|-75.6972|20
CA|Calgary|51.0447|-114.0719|20
AF|Kabul|34.5553|69.2075|25
AL|Tirana|41.3275|19.8187|20
DZ|Argel|36.7538|3.0588|25
AS|Pago Pago|-14.2756|-170.7020|10
AD|Andorra la Vella|42.5063|1.5218|8
AO|Luanda|-8.8390|13.2894|30
AI|The Valley|18.2172|-63.0578|8
AG|Saint John's|17.1274|-61.8468|10
AM|Ereván|40.1872|44.5152|20
AW|Oranjestad|12.5092|-70.0086|12
AU|Canberra|-35.2809|149.1300|20
AU|Sídney|-33.8688|151.2093|40
AU|Melbourne|-37.8136|144.9631|40
AT|Viena|48.2082|16.3738|25
AZ|Bakú|40.4093|49.8671|25
BS|Nasáu|25.0443|-77.3504|15
BH|Manama|26.2285|50.5860|15
BD|Daca|23.8103|90.4125|30
BB|Bridgetown|13.0975|-59.6167|12
BY|Minsk|53.9006|27.5590|25
BE|Bruselas|50.8503|4.3517|20
BZ|Belmopán|17.2510|-88.7590|10
BZ|Ciudad de Belice|17.5046|-88.1962|12
BJ|Porto Novo|6.4969|2.6289|12
BJ|Cotonú|6.3703|2.3912|15
BM|Hamilton|32.2949|-64.7814|12
BT|Timbu|27.4728|89.6390|12
BA|Sarajevo|43.8563|18.4131|15
BW|Gaborone|-24.6282|25.9231|15
IO|Diego Garcia|-7.3133|72.4111|10
VG|Road Town|18.4286|-64.6185|10
BN|Bandar Seri Begawan|4.9031|114.9398|15
BG|Sofía|42.6977|23.3219|20
BF|Uagadugú|12.3714|-1.5197|20
BI|Buyumbura|-3.3614|29.3599|15
BI|Gitega|-3.4271|29.9246|10
KH|Nom Pen|11.5564|104.9282|20
CM|Yaundé|3.8480|11.5021|20
CM|Duala|4.0511|9.7679|20
CV|Praia|14.9330|-23.5133|10
BQ|Kralendijk|12.1443|-68.2655|10
KY|George Town|19.2869|-81.3674|12
CF|Bangui|4.3947|18.5582|15
TD|Yamena|12.1348|15.0557|15
CN|Pekín|39.9042|116.4074|50
CN|Shanghái|31.2304|121.4737|50
CN|Cantón|23.1291|113.2644|40
CN|Shenzhen|22.5431|114.0579|30
CX|Flying Fish Cove|-10.4217|105.6791|8
CC|West Island|-12.1880|96.8290|8
KM|Moroni|-11.7172|43.2473|10
CD|Kinsasa|-4.4419|15.2663|8
CG|Brazzaville|-4.2634|15.2429|8
CK|Avarua|-21.2075|-159.7750|8
CI|Abiyán|5.3600|-4.0083|25
CI|Yamusukro|6.8276|-5.2893|12
HR|Zagreb|45.8150|15.9819|20
CW|Willemstad|12.1091|-68.9316|15
CY|Nicosia|35.1856|33.3823|15
CZ|Praga|50.0755|14.4378|25
DK|Copenhague|55.6761|12.5683|20
DJ|Yibuti|11.5721|43.1456|12
DM|Roseau|15.3092|-61.3794|10
EG|El Cairo|30.0444|31.2357|40
GQ|Malabo|3.7504|8.7371|12
GQ|Bata|1.8639|9.7658|12
ER|Asmara|15.3229|38.9251|15
EE|Tallin|59.4370|24.7536|15
ET|Adís Abeba|8.9806|38.7578|25
FK|Stanley|-51.6977|-57.8517|8
FO|Tórshavn|62.0079|-6.7909|8
FJ|Suva|-18.1248|178.4501|15
FI|Helsinki|60.1699|24.9384|20
FR|París|48.8566|2.3522|30
FR|Lyon|45.7640|4.8357|20
FR|Marsella|43.2965|5.3698|20
GF|Cayena|4.9224|-52.3135|12
PF|Papeete|-17.5516|-149.5585|12
GA|Libreville|0.4162|9.4673|15
GM|Banjul|13.4549|-16.5790|12
GE|Tiflis|41.7151|44.8271|20
DE|Berlín|52.5200|13.4050|30
DE|Múnich|48.1351|11.5820|25
DE|Fráncfort|50.1109|8.6821|20
DE|Hamburgo|53.5511|9.9937|25
GH|Acra|5.6037|-0.1870|25
GI|Gibraltar|36.1408|-5.3536|4
GR|Atenas|37.9838|23.7275|25
GL|Nuuk|64.1814|-51.6941|8
GD|Saint George's|12.0561|-61.7488|10
GP|Pointe-à-Pitre|16.2411|-61.5331|12
GP|Basse-Terre|15.9985|-61.7255|8
GU|Hagåtña|13.4757|144.7489|15
GG|Saint Peter Port|49.4542|-2.5367|8
GN|Conakri|9.6412|-13.5784|15
GW|Bisáu|11.8817|-15.6170|12
GY|Georgetown|6.8013|-58.1551|15
HT|Puerto Príncipe|18.5944|-72.3074|20
HK|Hong Kong|22.3193|114.1694|25
HU|Budapest|47.4979|19.0402|25
IS|Reikiavik|64.1466|-21.9426|15
IN|Nueva Delhi|28.6139|77.2090|40
IN|Bombay|19.0760|72.8777|40
ID|Yakarta|-6.2088|106.8456|40
IR|Teherán|35.6892|51.3890|35
IQ|Bagdad|33.3152|44.3661|30
IE|Dublín|53.3498|-6.2603|20
IM|Douglas|54.1523|-4.4861|8
IL|Jerusalén|31.7683|35.2137|15
IL|Tel Aviv|32.0853|34.7818|20
IT|Roma|41.9028|12.4964|30
IT|Milán|45.4642|9.1900|25
JM|Kingston|17.9712|-76.7936|20
JP|Tokio|35.6762|139.6503|50
JE|Saint Helier|49.1868|-2.1063|8
JO|Amán|31.9454|35.9284|25
KZ|Astaná|51.1694|71.4491|20
KZ|Almaty|43.2220|76.8512|25
KE|Nairobi|-1.2921|36.8219|25
KI|Tarawa Sur|1.4518|172.9717|10
XK|Pristina|42.6629|21.1655|12
KW|Ciudad de Kuwait|29.3759|47.9774|25
KG|Biskek|42.8746|74.5698|15
LA|Vientián|17.9757|102.6331|15
LV|Riga|56.9496|24.1052|20
LB|Beirut|33.8938|35.5018|15
LS|Maseru|-29.3151|27.4869|12
LR|Monrovia|6.3156|-10.8074|15
LY|Trípoli|32.8872|13.1913|25
LI|Vaduz|47.1410|9.5209|8
LT|Vilna|54.6872|25.2797|15
LU|Luxemburgo|49.6116|6.1319|12
MO|Macao|22.1987|113.5439|8
MK|Skopie|41.9981|21.4254|15
MG|Antananarivo|-18.8792|47.5079|20
MW|Lilongüe|-13.9626|33.7741|15
MY|Kuala Lumpur|3.1390|101.6869|30
MV|Malé|4.1755|73.5093|8
ML|Bamako|12.6392|-8.0029|20
MT|La Valeta|35.8989|14.5146|12
MH|Majuro|7.0897|171.3803|10
MQ|Fort-de-France|14.6161|-61.0588|12
MR|Nuakchot|18.0735|-15.9582|15
MU|Port Louis|-20.1609|57.5012|15
YT|Mamoudzou|-12.7806|45.2279|8
FM|Palikir|6.9248|158.1611|10
MD|Chisináu|47.0105|28.8638|15
MC|Mónaco|43.7384|7.4246|3
MN|Ulán Bator|47.8864|106.9057|20
ME|Podgorica|42.4304|19.2594|12
MS|Brades|16.7928|-62.2106|8
MA|Rabat|34.0209|-6.8416|20
MA|Casablanca|33.5731|-7.5898|25
MZ|Maputo|-25.9692|32.5732|20
MM|Naipyidó|19.7633|96.0785|20
MM|Rangún|16.8409|96.1735|25
NA|Windhoek|-22.5609|17.0658|15
NR|Yaren|-0.5477|166.9209|5
NP|Katmandú|27.7172|85.3240|20
NL|Ámsterdam|52.3676|4.9041|20
NL|La Haya|52.0705|4.3007|12
NL|Róterdam|51.9244|4.4777|15
NC|Numea|-22.2758|166.4580|12
NZ|Wellington|-41.2865|174.7762|15
NZ|Auckland|-36.8485|174.7633|25
NE|Niamey|13.5116|2.1254|15
NG|Abuya|9.0765|7.3986|25
NG|Lagos|6.5244|3.3792|35
NU|Alofi|-19.0544|-169.8672|8
NF|Kingston|-29.0564|167.9597|6
KP|Pionyang|39.0392|125.7625|20
MP|Saipán|15.1778|145.7508|10
NO|Oslo|59.9139|10.7522|20
OM|Mascate|23.5880|58.3829|25
PK|Islamabad|33.6844|73.0479|20
PK|Karachi|24.8607|67.0011|35
PW|Koror|7.3419|134.4792|10
PS|Ramala|31.9038|35.2034|10
PS|Gaza|31.5017|34.4668|10
PG|Port Moresby|-9.4438|147.1803|15
PH|Manila|14.5995|120.9842|30
PL|Varsovia|52.2297|21.0122|25
PT|Lisboa|38.7223|-9.1393|25
PT|Oporto|41.1579|-8.6291|20
QA|Doha|25.2854|51.5310|25
RE|Saint-Denis|-20.8789|55.4481|12
RO|Bucarest|44.4268|26.1025|25
RU|Moscú|55.7558|37.6173|40
RU|San Petersburgo|59.9343|30.3351|30
RW|Kigali|-1.9441|30.0619|15
BL|Gustavia|17.8962|-62.8498|6
SH|Jamestown|-15.9244|-5.7181|6
KN|Basseterre|17.3026|-62.7177|8
LC|Castries|14.0101|-60.9875|10
MF|Marigot|18.0708|-63.0501|6
PM|Saint-Pierre|46.7811|-56.1764|6
VC|Kingstown|13.1600|-61.2248|8
WS|Apia|-13.8333|-171.7667|10
SM|San Marino|43.9424|12.4578|6
ST|Santo Tomé|0.3365|6.7273|8
SA|Riad|24.7136|46.6753|35
SA|Yeda|21.4858|39.1925|30
SN|Dakar|14.7167|-17.4677|20
RS|Belgrado|44.7866|20.4489|20
SC|Victoria|-4.6191|55.4513|8
SL|Freetown|8.4657|-13.2317|15
SG|Singapur|1.3521|103.8198|25
SX|Philipsburg|18.0260|-63.0458|6
SK|Bratislava|48.1486|17.1077|15
SI|Liubliana|46.0569|14.5058|12
SB|Honiara|-9.4456|159.9729|10
SO|Mogadiscio|2.0469|45.3182|20
ZA|Johannesburgo|-26.2041|28.0473|35
ZA|Pretoria|-25.7479|28.2293|20
ZA|Ciudad del Cabo|-33.9249|18.4241|30
KR|Seúl|37.5665|126.9780|35
SS|Yuba|4.8594|31.5713|15
LK|Colombo|6.9271|79.8612|20
SD|Jartum|15.5007|32.5599|25
SR|Paramaribo|5.8520|-55.2038|15
SJ|Longyearbyen|78.2232|15.6267|6
SZ|Mbabane|-26.3054|31.1367|10
SE|Estocolmo|59.3293|18.0686|25
CH|Berna|46.9480|7.4474|12
CH|Zúrich|47.3769|8.5417|20
CH|Ginebra|46.2044|6.1432|15
SY|Damasco|33.5138|36.2765|20
TW|Taipéi|25.0330|121.5654|25
TJ|Dusambé|38.5598|68.7870|15
TZ|Dodoma|-6.1630|35.7516|15
TZ|Dar es-Salam|-6.7924|39.2083|30
TH|Bangkok|13.7563|100.5018|40
TL|Dili|-8.5569|125.5603|10
TG|Lomé|6.1725|1.2314|15
TK|Fakaofo|-9.3803|-171.2188|5
TO|Nukualofa|-21.1394|-175.2049|10
TT|Puerto España|10.6596|-61.5089|12
TT|San Fernando|10.2797|-61.4589|10
TT|Chaguanas|10.5168|-61.4114|8
TN|Túnez|36.8065|10.1815|20
TR|Ankara|39.9334|32.8597|30
TR|Estambul|41.0082|28.9784|40
TM|Asjabad|37.9601|58.3261|15
TC|Cockburn Town|21.4612|-71.1419|6
TV|Funafuti|-8.5211|179.1983|5
VI|Charlotte Amalie|18.3419|-64.9307|10
UG|Kampala|0.3476|32.5825|20
UA|Kiev|50.4501|30.5234|30
AE|Abu Dabi|24.4539|54.3773|30
AE|Dubái|25.2048|55.2708|30
GB|Londres|51.5074|-0.1278|35
GB|Mánchester|53.4808|-2.2426|20
UZ|Taskent|41.2995|69.2401|20
VU|Port Vila|-17.7333|168.3273|10
VA|Ciudad del Vaticano|41.9029|12.4534|1
VN|Hanói|21.0278|105.8342|30
VN|Ciudad Ho Chi Minh|10.8231|106.6297|35
WF|Mata-Utu|-13.2825|-176.1736|6
EH|El Aaiún|27.1418|-13.1875|12
YE|Saná|15.3694|44.1910|20
YE|Adén|12.7855|45.0187|15
ZM|Lusaka|-15.3875|28.3228|20
ZW|Harare|-17.8252|31.0335|20
"""


def rows():
    for line in CITIES.strip().splitlines():
        cc, city, lat, lng, radius = line.split('|')
        yield cc, city, Decimal(lat).quantize(Decimal('0.000001')), Decimal(lng).quantize(Decimal('0.000001')), int(radius)


def seed(apps, schema_editor):
    from exchange_rates.currency_mapping import COUNTRY_TO_CURRENCY

    City = apps.get_model('marketplace', 'MarketplaceCity')
    for cc, city, lat, lng, radius in rows():
        # An existing row (any spelling case) is left exactly as it is.
        if City.objects.filter(country_code=cc, city__iexact=city).exists():
            continue
        City.objects.create(
            country_code=cc, city=city, currency_code=COUNTRY_TO_CURRENCY.get(cc, 'USD')[:3],
            is_live=True, delivery_estimate=None, delivery_partner='',
            latitude=lat, longitude=lng, radius_km=radius)


def unseed(apps, schema_editor):
    """Removes only the rows this migration created and nobody edited since
    (still live, no estimate, no area): an admin's change survives."""
    City = apps.get_model('marketplace', 'MarketplaceCity')
    for cc, city, lat, lng, radius in rows():
        City.objects.filter(country_code=cc, city=city, latitude=lat, longitude=lng, radius_km=radius,
                            is_live=True, delivery_estimate__isnull=True, delivery_area='').delete()


class Migration(migrations.Migration):
    dependencies = [('marketplace', '0017_alcohol_licence_approvals')]
    operations = [
        migrations.AlterField(
            model_name='marketplacecity', name='is_live',
            field=models.BooleanField(default=True,
                                      help_text='Off = closed: the fake door ("Próximamente en tu ciudad")')),
        migrations.RunPython(seed, unseed),
    ]
