"""What may be remembered, as pure rules: no database, no model.

A preference is a value from a closed list. There is no free text, not even a
name. The summary is ids of the person's own messages, and a message gets
there through three gates, each failing closed:

1. it is shaped like a statement about the person's own plans, studies,
   projects, hobbies, pets, events or goals (an allow-list: anything else,
   including every language but Spanish and Portuguese, stays out);
2. it has none of the words of secrets, money, documents, addresses,
   sensitive traits, instructions or someone else speaking;
3. a model with no tools puts it in one of the closed topics (memory.py).

Gates 1 and 2 run again every time it is read. See docs/designs/assistant-memory.md.
"""
from __future__ import annotations

import re
import unicodedata

LANGUAGE, LENGTH, LEVEL, ADDRESS = 'reply_language', 'reply_length', 'explanations', 'address'
GOAL, WORK, FAMILY, INTEREST = 'goal', 'occupation', 'family_in', 'interest'

# kind -> value -> how it is shown to the person.
VALUES = {
    LANGUAGE: {'es': 'Responderte en español', 'pt': 'Responderte en portugués', 'en': 'Responderte en inglés'},
    LENGTH: {'short': 'Darte respuestas cortas', 'detailed': 'Darte respuestas detalladas'},
    LEVEL: {'beginner': 'Explicarte desde lo básico', 'experienced': 'Explicarte como a alguien con experiencia'},
    ADDRESS: {'tu': 'Tratarte de tú', 'usted': 'Tratarte de usted', 'vos': 'Tratarte de vos',
              'voce': 'Tratarte de você'},
    GOAL: {
        'emergency_fund': 'Meta: fondo de emergencia', 'travel': 'Meta: un viaje', 'home': 'Meta: una vivienda',
        'vehicle': 'Meta: un vehículo', 'studies': 'Meta: estudios', 'own_business': 'Meta: negocio propio',
        'family_support': 'Meta: apoyar a tu familia', 'wedding': 'Meta: una boda',
        'retirement': 'Meta: tu retiro', 'saving': 'Meta: ahorrar',
    },
    WORK: {'employee': 'Trabajas como empleado', 'freelancer': 'Trabajas por tu cuenta',
           'business_owner': 'Tienes un negocio', 'student': 'Estudias', 'homemaker': 'Te encargas del hogar'},
    FAMILY: {code: f'Tienes familia en {name}' for code, name in {
        'AR': 'Argentina', 'BO': 'Bolivia', 'BR': 'Brasil', 'CL': 'Chile', 'CO': 'Colombia', 'CR': 'Costa Rica',
        'CU': 'Cuba', 'DO': 'República Dominicana', 'EC': 'Ecuador', 'ES': 'España', 'GT': 'Guatemala',
        'HN': 'Honduras', 'MX': 'México', 'NI': 'Nicaragua', 'PA': 'Panamá', 'PE': 'Perú', 'PR': 'Puerto Rico',
        'PY': 'Paraguay', 'SV': 'El Salvador', 'US': 'Estados Unidos', 'UY': 'Uruguay', 'VE': 'Venezuela',
    }.items()},
    INTEREST: {'football': 'Te gusta el fútbol', 'cooking': 'Te gusta la cocina', 'music': 'Te gusta la música',
               'travel': 'Te gusta viajar', 'reading': 'Te gusta leer', 'movies': 'Te gustan las películas',
               'games': 'Te gustan los videojuegos', 'technology': 'Te gusta la tecnología',
               'animals': 'Te gustan los animales'},
}
KINDS = tuple(VALUES)
MANY = frozenset({GOAL, FAMILY, INTEREST})
MANY_MAX = 3

# How to answer is said to the model in these sentences, written here and picked by value.
STYLE = {
    (LANGUAGE, 'es'): 'IDIOMA: escribe toda tu respuesta en español, aunque la pregunta o los mensajes anteriores '
                      'estén en otro idioma. Solo cambia si ahora pide otro idioma.',
    (LANGUAGE, 'pt'): 'IDIOMA OBRIGATÓRIO: escreva toda a sua resposta em português do Brasil. A pergunta, as '
                      'mensagens anteriores e estas instruções podem estar em espanhol: mesmo assim, responda em '
                      'português. Só mude se a pessoa pedir outro idioma agora.',
    (LANGUAGE, 'en'): 'REQUIRED LANGUAGE: write your whole answer in English. The question, the earlier messages '
                      'and these instructions may be in Spanish: answer in English anyway. Change only if the '
                      'person asks for another language now.',
    (LENGTH, 'short'): 'Responde corto: una a tres frases, salvo que ahora pida más.',
    (LENGTH, 'detailed'): 'Responde con detalle.',
    (LEVEL, 'beginner'): 'Explica desde lo básico, sin tecnicismos.',
    (LEVEL, 'experienced'): 'Explica como a alguien con experiencia, sin lo básico.',
    (ADDRESS, 'tu'): 'Trata a la persona de tú.',
    (ADDRESS, 'usted'): 'Trata a la persona de usted.',
    (ADDRESS, 'vos'): 'Trata a la persona de vos.',
    (ADDRESS, 'voce'): 'Trate a pessoa por você.',
}
STYLE_KINDS = frozenset(kind for kind, _ in STYLE)

QUOTE_MAX_CHARS = 160
COMMAND_MAX_CHARS = 200

# Renders as nothing, still readable by a model: never part of a match or a quote.
_INVISIBLE = re.compile(r'[­͏؜ᅟᅠ᠋-᠏​-‏‪-‮⁠-⁯'
                        r'ㅤ︀-️﻿\U000e0000-\U000e0fff]')


def visible(text) -> str:
    return _INVISIBLE.sub('', unicodedata.normalize('NFKC', str(text or '')))


def fold(text) -> str:
    """Lower case, no accents, one line."""
    plain = ''.join(c for c in unicodedata.normalize('NFD', visible(text).lower())
                    if unicodedata.category(c) != 'Mn')
    return ' '.join(plain.split())


def words_of(text) -> str:
    """Only the words, for matching a request however it was punctuated."""
    return ' '.join(re.findall(r'[a-z0-9]+', fold(text)))


def _any(*parts):
    return re.compile(r'\b(?:' + '|'.join(parts) + r')\b')


# ── Gate 2: what is never kept ─────────────────────────────────────────────

SENSITIVE = _any(
    # health
    r'salud', r'saude', r'health', r'enferm\w*', r'doenc\w*', r'doentes?', r'illness', r'sick', r'diagnos\w*',
    r'cancer\w*', r'tumor\w*', r'leucemi\w*', r'diabet\w*', r'vih', r'hiv', r'sida', r'aids', r'\w*positiv[oa]s?',
    r'sifilis', r'tubercul\w*', r'covid', r'parkinson', r'alzheimer', r'sindrome', r'esquizo\w*', r'bipolar\w*',
    r'depre\w*', r'antidepre\w*', r'ansiedad', r'ansiedade', r'anorexi\w*', r'bulimi\w*', r'sobrepeso',
    r'obesidad\w*', r'embaraz\w*', r'gravid\w*', r'gestante', r'posparto', r'bebe', r'pregnan\w*', r'aborto\w*',
    r'terap\w*', r'therap\w*', r'psic\w*', r'psiqu\w*', r'medic[oa]s?', r'medicamento\w*', r'doctor\w*',
    r'hospital\w*', r'clinicas?', r'cirug\w*', r'cirurg\w*', r'oper(?:ar|aron|aram|ado|ada|acion)\w*', r'quimio\w*',
    r'dialisis', r'insulina', r'\w*quimios?', r'radioterap\w*', r'protesis', r'protese', r'tdah', r'toc', r'panico',
    r'fertiliza\w*', r'discapac\w*', r'deficien\w*', r'disabilit\w*', r'silla de ruedas', r'sord[oa]s?',
    r'cieg[oa]s?', r'autis\w*', r'alergi\w*', r'asma', r'epilep\w*', r'celiac\w*', r'lupus', r'migran[ae]s?',
    r'hipertens\w*', r'infart\w*', r'presion alta', r'adict\w*', r'adicc\w*', r'viciad\w*', r'alcohol\w*',
    r'drog\w*', r'marihuana', r'maconha', r'suicid\w*', r'pastillas?', r'remedio', r'tratamiento', r'tratamento',
    r'vacun\w*', r'sintom\w*', r'menstrua\w*', r'me pega', r'abus[oa]\w*', r'violencia', r'funeral', r'velorio',
    # politics, unions
    r'politic\w*', r'partido politico', r'vot[aeo]\w*', r'elecci\w*', r'eleic\w*', r'gobierno', r'governo',
    r'marcha', r'manifest\w*', r'protesta\w*', r'maduro', r'chavis\w*', r'madurist\w*', r'opositor\w*', r'oposici\w*',
    r'peronis\w*', r'kirchner\w*', r'milei\w*', r'bolsonar\w*', r'lula', r'lulist\w*', r'petist\w*', r'petrist\w*',
    r'morena', r'morenist\w*', r'masist\w*', r'uribis\w*', r'comunis\w*', r'socialis\w*', r'derechas?', r'direita',
    r'izquierd\w*', r'esquerda', r'sindica\w*', r'trump',
    # religion
    r'religi\w*', r'dios', r'deus', r'cristo', r'jesus', r'jehova', r'jeova', r'iglesias?', r'igrejas?', r'templo',
    r'catolic\w*', r'cristian[oa]s?', r'cristianismo', r'cristaos?', r'evangelic\w*', r'evangelho', r'evangelio',
    r'protestante\w*', r'espirit\w*', r'musulm\w*', r'muculman\w*', r'islam\w*', r'judi\w*', r'judeu', r'ateos?',
    r'ateu', r'atea', r'mormon\w*', r'testigo\w*', r'budis\w*', r'biblia', r'biblic\w*', r'misa', r'missa', r'cultos?',
    r'oracion', r'oracao', r'rezo', r'rezar', r'predic\w*', r'pastor', r'congrega\w*', r'sinagoga', r'mezquita',
    r'mesquita', r'umbanda', r'candomble', r'santeria', r'church', r'ramadan', r'bautiz\w*', r'batiz\w*',
    r'primera comunion', r'peregrin\w*', r'senor', r'senhor', r'rehabilitaci\w*', r'reabilitac\w*', r'enamorad[oa]s?',
    r'movimiento (?:por|de)', r'libertad', r'liberdade', r'salir del pais', r'sair do pais', r'rabin\w*', r'terreiro', r'meca', r'seminario', r'sacerdote', r'monja',
    # sexuality, gender
    r'gays?', r'lesbi\w*', r'lesbic\w*', r'homosex\w*', r'bisex\w*', r'transex\w*', r'transgen\w*', r'trans',
    r'lgbt\w*', r'queer', r'no binari[oa]', r'nao binari[oa]', r'orientacion sexual', r'drag', r'orgullo', r'orgulho',
    r'novi[oa]s?', r'namorad[oa]s?', r'espos[oa]s?', r'marido', r'transicion', r'transicao',
    # ethnicity, immigration, criminal record
    r'indigena\w*', r'etnia', r'raza', r'raca', r'negr[oa]s?', r'afro\w*', r'aymara', r'quechua', r'mapuche',
    r'guarani', r'documentad\w*', r'undocumented', r'indocument\w*', r'inmigra\w*', r'imigra\w*', r'frontera',
    r'fronteira', r'ilegal\w*', r'deport\w*', r'refugi\w*', r'asilo', r'visas?', r'visto', r'ciudadania',
    r'cidadania', r'tps', r'parole', r'papeles', r'antecedentes', r'pres[oa]s?', r'presidi\w*', r'carcel', r'cadeia',
    r'prisao', r'prision', r'detenid\w*', r'condena\w*', r'juicio', r'bancarrota', r'quiebra', r'falencia',
)
SECRET = _any(
    r'clave\w*', r'contrasen\w*', r'senhas?', r'passwords?', r'palavra passe', r'pass', r'pins?', r'cvv', r'cvc',
    r'tokens?', r'otp', r'codigos?', r'code', r'palabra secreta', r'secret[oa]s?', r'resposta de seguranca',
    r'patron de desbloqueo', r'frase (?:semilla|de recuperacion|secreta)', r'semillas?', r'seed', r'mnemonic\w*',
    r'recuperac\w*', r'private key', r'chaves?', r'llave', r'copia e cola', r'documentos?', r'identidad',
    r'identidade', r'cedulas?', r'dni', r'cpf', r'cnpj', r'curp', r'rfc', r'pasaportes?', r'passaportes?',
    r'carnet', r'licencia', r'rut', r'nit', r'cbu', r'cvu', r'clabe', r'iban', r'swift', r'tarjetas?', r'cartao',
    r'cartoes', r'cuentas?', r'contas?', r'numeros?', r'arroba', r'correo', r'email', r'telefono', r'telefone',
    r'celular',
)
ADDRESS_WORDS = _any(
    r'calles?', r'avenidas?', r'av', r'carrera \w*\d+', r'cra', r'transversal', r'manzana', r'callejon\w*',
    r'urbanizacion', r'urb', r'barrio', r'colonia', r'sector', r'conjunto', r'torres?', r'edificio', r'apartamento',
    r'apto', r'rua', r'travessa', r'vila', r'bairro', r'endereco', r'cep', r'direccion', r'domicilio', r'residencia',
    r'resid[oe]', r'condominio', r'casa \w+ junto', r'quadra', r'address', r'esquina', r'frente a', r'al lado de', r'vivo', r'vivimos', r'moro', r'moramos',
)
MONEY = _any(
    r'mand\w*', r'envi\w*', r'transf\w*', r'pag\w*', r'pas(?:a|e|ale|ales|ame)', r'dale', r'hazle', r'retir\w*',
    r'sacar', r'saque', r'compr\w*', r'vend(?:o|e|er|a|ele|ere|i|as|amos)', r'deposit\w*', r'cobr\w*', r'confirm\w*',
    r'autori[sz]\w*', r'aprob\w*', r'aprueb\w*', r'aprov\w*', r'approv\w*', r'reglas?', r'regras?', r'alertas?',
    r'destinatari\w*', r'beneficiari\w*', r'gir(?:a|ar|arle|ale|o|e)', r'abon\w*', r'liber(?:a|e|ar|ado|ada|o)',
    r'monto', r'valor', r'contato', r'contacto', r'yape\w*', r'plin', r'zelle', r'nequi', r'daviplata', r'pix', r'qr',
    r'binance', r'usdt', r'usdc', r'cripto\w*', r'bitcoin', r'acciones', r'acoes', r'etfs?', r'invert\w*', r'invers\w*',
    r'invest\w*', r'prestam\w*', r'emprestimo', r'deud\w*', r'divida\w*', r'dinero', r'dinheiro', r'plata', r'grana',
    r'banco', r'recarg\w*', r'saldos?', r'balances?', r'patrimonio', r'sueldos?', r'salarios?', r'ingresos?', r'gano',
    r'ganho', r'gana', r'mensual\w*', r'mensais', r'junte', r'juntei', r'ahorrad[oa]s?', r'guardad[oa]s?',
    r'dolar\w*', r'dollar\w*', r'usd\w*', r'cusd', r'bs', r'bolivares', r'bolivianos', r'pesos?', r'reais', r'soles',
    r'euros?', r'lucas', r'palos', r'quetzales',
    # number words big enough to be an amount
    r'veint\w+', r'vinte', r'treinta', r'trinta', r'cuarenta', r'quarenta', r'cincuenta', r'cinquenta', r'sesenta',
    r'sessenta', r'setenta', r'ochenta', r'oitenta', r'noventa', r'cien', r'ciento', r'cem', r'cento', r'\w*cientos',
    r'\w*centos', r'quinientos', r'mil', r'miles', r'millon\w*', r'milhao', r'milhoes',
)
_SPOKEN_DIGIT = _any(r'cero', r'zero', r'uno', r'dos', r'dois', r'tres', r'cuatro', r'quatro', r'cinco', r'seis',
                     r'siete', r'sete', r'ocho', r'oito', r'nueve', r'nove', r'diez', r'dez', r'once', r'doce',
                     r'doze', r'trece', r'treze', r'catorce', r'quince', r'quinze')
# Someone else's words, or an order to the assistant, or a voice with authority.
NOT_THEIR_STATEMENT = _any(
    r'dice', r'dicen', r'dijo', r'dijeron', r'diz', r'disse', r'disseram', r'segun', r'segundo o', r'segundo a',
    r'escribi(?:o|eron)', r'escreveu', r'mandaron', r'reenvi\w*', r'encaminh\w*', r'copie', r'copiei', r'colei',
    r'nota', r'mensaje', r'mensagem', r'llego un', r'recebi',
    r'confio', r'equipe', r'equipo (?:de soporte|tecnico)', r'el equipo', r'soporte', r'suporte', r'staff', r'admin\w*',
    r'moderador\w*', r'sistema', r'system', r'prompt', r'developer', r'desarrollador\w*', r'desenvolvedor\w*',
    r'assistant', r'asistente', r'assistente', r'oficial', r'verificad[oa]', r'instruc\w*', r'orientac\w*', r'ignor\w*',
    r'omit\w*', r'verificac\w*', r'evadir', r'evitar', r'saltar(?:me|se)?', r'burlar', r'advert\w*', r'avise\w*', r'estafas?', r'golpes?', r'obedec\w*', r'jailbreak', r'fing\w*', r'finj\w*',
    r'actua', r'responde\w*', r'responda', r'contesta\w*', r'siempre', r'sempre', r'nunca', r'sin preguntar',
    r'sem perguntar', r'a partir de', r'de ahora', r'desde ahora', r'de agora', r'debes', r'tienes que', r'eres',
    r'seras', r'quiero que', r'quero que', r'necesito que', r'preciso que',
    # spoken to the assistant: a request, not a statement
    r'te', r'ti', r'tu', r'tus', r'contigo', r'usted', r'ustedes', r'voce', r'voces', r'vc', r'vos',
)
# "cuenta" that is no account.
_IDIOMS = _any(r'por mi cuenta', r'por conta propria', r'(?:ten|tenga|tener|tomar) en cuenta')
_PLAIN_CHARS = re.compile(r"[a-z0-9 ,.!¡'\"()-]*")
_SPELLED_OUT = re.compile(r'(?:\b[a-z]\b[ .,-]*){4,}')


def never_kept(text) -> bool:
    """Secrets, documents, codes, addresses, amounts in digits and sensitive traits."""
    folded, plain = fold(text), words_of(text)
    if sum(c.isdigit() for c in folded) > 3 or re.search(r'[a-z]\d|\d[a-z]|@|://|www\.|\S{25,}', folded):
        return True
    if any(c.isalpha() and not ('a' <= c <= 'z') for c in folded) or _SPELLED_OUT.search(folded):
        return True  # a look-alike alphabet or spelled-out letters would walk past every list
    return bool(SENSITIVE.search(plain) or SECRET.search(_IDIOMS.sub(' ', plain)) or ADDRESS_WORDS.search(plain)
                or len(_SPOKEN_DIGIT.findall(plain)) >= 3)


# ── Gate 1: a statement about the person's own everyday life ───────────────

_LEAD = r'^(?:(?:hola|oye|bueno|pues|ah|y|e|oi|ola|entao|tambien|tambem|ahora|agora|por cierto|alias) )*(?:yo |eu )?'
_FIRST_PERSON = re.compile(_LEAD + r'(?:' + '|'.join((
    r'estoy', r'ando', r'sigo', r'empece a', r'comence a', r'voy a', r'me voy', r'vamos a', r'ya no', r'no voy a',
    r'cancele', r'quiero', r'quisiera', r'me gustaria', r'pienso', r'planeo', r'necesito organizar', r'me mudo',
    r'viajo', r'estudio', r'aprendo', r'preparo', r'toco', r'juego', r'me gusta', r'me encanta', r'me interesa',
    r'soy fan', r'tengo (?:un|una|dos)',
    r'estou', r'to', r'comecei a', r'vou', r'vamos', r'nao vou', r'cancelei', r'quero', r'queria', r'gostaria de',
    r'pretendo', r'planejo', r'estudo', r'gosto de', r'adoro', r'curto', r'tenho (?:um|uma|dois|duas)',
)) + r')\b')
_TOPIC = _any(
    r'viaj\w*', r'viagem', r'vacaciones', r'ferias', r'paseo', r'passeio', r'mudar\w*', r'mudando', r'mudanca',
    r'mudo', r'estudi\w*', r'estud(?:o|ar|ando)', r'aprend\w*', r'tesis', r'tese', r'examen', r'exame', r'prova',
    r'concurso', r'curso', r'universidad', r'universidade', r'facultad', r'faculdade', r'idiomas?', r'ingles',
    r'frances', r'programar', r'programacion', r'programacao', r'montar', r'montando', r'abrir', r'emprend\w*',
    r'negocio', r'tienda', r'loja', r'cafeteria', r'confeitaria', r'panaderia', r'padaria', r'restaurante',
    r'empanadas', r'proyecto', r'projeto', r'escribiendo', r'escribir', r'escrevendo', r'escrever', r'blog',
    r'podcast', r'libros?', r'livros?', r'leer', r'leyendo', r'lendo', r'novela', r'romance', r'peliculas?',
    r'filmes?', r'series?', r'musica', r'guitarra', r'violao', r'piano', r'bateria', r'cantar', r'bailar', r'dancar',
    r'cocin\w*', r'cozinh\w*', r'futbol', r'futebol', r'correr', r'maraton', r'maratona', r'ciclismo', r'nadar',
    r'dibuj\w*', r'desenhar', r'pintar', r'fotografia', r'jardin', r'jardim', r'videojuegos?', r'perr[oa]s?',
    r'gat[oa]s?', r'cachorr[oa]s?', r'mascotas?', r'boda', r'casamento', r'fiesta', r'festa', r'cumpleanos',
    r'aniversario', r'graduacion', r'formatura', r'ahorrar', r'poupar', r'juntar', r'moto', r'carro', r'casa propia',
)
# "mi" and "meu" open a statement only right before one of the person's own things.
_MINE = re.compile(_LEAD + r'(?:mi|mis|meu|meus|minha|minhas) (?:' + '|'.join((
    r'perr[oa]s?', r'gat[oa]s?', r'cachorr[oa]s?', r'mascotas?', r'equipo favorito', r'time favorito',
    r'time do coracao', r'negocio', r'tienda', r'loja', r'confeitaria', r'proyecto', r'projeto', r'tesis', r'tese',
    r'meta', r'sueno es', r'sonho e', r'viaje', r'viagem', r'curso', r'examen', r'boda', r'casamento', r'hobby',
    r'libro favorito', r'livro favorito', r'pelicula favorita', r'filme favorito',
)) + r')\b')
_FUNCTION_WORDS = _any(r'el', r'la', r'los', r'las', r'un', r'una', r'de', r'del', r'en', r'a', r'con', r'para',
                       r'por', r'que', r'y', r'mi', r'mis', r'o', r'os', r'as', r'um', r'uma', r'do', r'da', r'no',
                       r'na', r'com', r'pra', r'e', r'meu', r'minha', r'se', r'es', r'me')


def quotable(text) -> bool:
    """Gates 1 and 2: may this message of the person's own be quoted back later?"""
    raw = str(text or '').strip()
    if not raw or len(raw) > QUOTE_MAX_CHARS or '\n' in raw or not _PLAIN_CHARS.fullmatch(fold(raw)):
        return False  # a paste, a question, a label ("Nota: …"), an odd character
    plain = words_of(raw)
    count = len(plain.split())
    if count < 3 or not (_MINE.match(plain) or (_FIRST_PERSON.match(plain) and _TOPIC.search(plain))):
        return False
    run = longest = 0
    for word in plain.split():
        run = 0 if _FUNCTION_WORDS.fullmatch(word) else run + 1
        longest = max(longest, run)
    if longest >= 7 or (count >= 10 and len(_FUNCTION_WORDS.findall(plain)) < 2):
        return False  # a run of bare words reads like a recovery phrase
    return not (never_kept(raw) or MONEY.search(plain) or NOT_THEIR_STATEMENT.search(plain))


def quote(text) -> str:
    """A quotable message as it is shown: one line, digits masked."""
    from .engine import third_party_text
    return third_party_text(re.sub(r'\d+(?:[.,]\d+)*', '#', visible(text)), QUOTE_MAX_CHARS)


# ── Explicit requests, matched on words_of() ───────────────────────────────

_PLEASE = (r'^(?:(?:por favor|porfa|porfavor|oye|oi|ola|hola|confio|confi|bueno|pues|ok|okay|okey|entonces|'
           r'entao|ya|e|y|please) )*')
_REMEMBER = re.compile(_PLEASE + r'(?:' + '|'.join((
    r'recuerda(?: siempre)? (?:que|q|mi|mis|tratarme|hablarme|responderme|explicarme)',
    r'recuerde que', r'acuerdate (?:de )?(?:que|q)', r'memoriza', r'no (?:te )?olvides (?:de )?(?:que|q)',
    r'ten (?:en cuenta|presente) (?:que|q)', r'tenga (?:en cuenta|presente) (?:que|q)', r'anota que',
    r'guarda (?:que|en (?:tu )?memoria)',
    r'(?:puedes|podrias|quiero que|necesito que) (?:te acuerdes (?:de )?que|recordar que|recuerdes que)',
    r'lembr[ae](?: se)? (?:de )?(?:que|meu|minha)', r'nao (?:se )?esquec[ae] (?:de )?que',
    r'guard[ae] (?:que|na (?:sua )?memoria)', r'(?:pode|quero que voce) (?:lembrar|lembre) (?:de )?que',
    r'remember (?:that|i|my)',
    r'prefiero (?:que me )?(?:respond|habl|trat|expliqu)\w*', r'prefiero respuestas', r'prefiro respostas',
    r'prefiro que (?:me )?(?:respond|fal|trat)\w*',
    r'(?:respondeme|respondame|responda me|hablame|fale comigo|tratame|trateme|me trate|explicame) (?:siempre|sempre)',
    r'(?:siempre|sempre|de ahora en adelante|a partir de (?:ahora|agora)|de agora em diante) '
    r'(?:me (?:respondas|responda|hables|hable|trates|trate|expliques|explique)|respondeme|hablame|tratame|'
    r'explicame|fale comigo)\b(?! (?:tarde|el|la|o|a) )',
)) + r')\b')

# Never "olvide", "borre" or "elimine": without the accent they are also "olvidé", "borré", "eliminé",
# something that already happened. Said that way, the screen is where to delete.
_FORGET_VERB = (r'(?:olvida(?:te|lo)?|olvidese de|(?:quiero|necesito) que (?:te )?olvides|'
                r'puedes olvidar(?:te)?|esquec[ae]|(?:pode|quero que voce) esquec(?:er|a)|forget)')
_ERASE_VERB = r'(?:borra(?:r|lo|melo)?|elimina|limpia|delete|clear|erase)'
# "apagar" deletes in Portuguese and only switches off in Spanish: never a delete without a Portuguese object.
_APAGA = r'(?:apaga|apague)'
_ABOUT_ME = r'(?: (?:de|sobre) (?:mi|mim)| about me)?'
_WHAT = (r'lo anterior|lo que (?:sabes|recuerdas|guardaste|hablamos|(?:te )?(?:dije|conte)|te he (?:dicho|contado))'
         r'|o que (?:eu |voce )?(?:te )?(?:disse|falei|contei|sabe|lembra|conversamos)|i (?:said|told you)')
_WIPE = re.compile(_PLEASE + '(?:' + '|'.join((
    rf'{_FORGET_VERB}(?: de)? (?:todo|tudo|everything)(?: (?:{_WHAT}))?' + _ABOUT_ME,
    # "borra todo" could mean anything on the screen, also said politely: only with what it is.
    rf'(?:{_ERASE_VERB} (?:todo|tudo|everything)|{_APAGA} tudo) (?!lo anterior)(?:{_WHAT})' + _ABOUT_ME,
    rf'(?:{_ERASE_VERB} (?:todo|tudo|everything)|{_APAGA} tudo) (?:de|sobre) (?:mi|mim)',
    rf'{_APAGA} (?:toda )?(?:a|a sua|sua|a minha|minha) memoria(?: (?:de|sobre) mim)?',
    rf'{_APAGA} o que (?:voce )?sabe(?: (?:de|sobre) mim)?',
    rf'(?:{_FORGET_VERB}|{_ERASE_VERB}) (?:toda |todas )?(?:(?:tu|la|mi|a|sua|a sua|minha|a minha|your|my) '
    r'(?:memoria|memory)|mis recuerdos|mis preferencias|minhas preferencias|nuestro chat|nossa conversa)' + _ABOUT_ME,
    rf'(?:{_FORGET_VERB}|{_ERASE_VERB}) (?:lo que|o que|what) (?:sabes|recuerdas|voce sabe|you know)' + _ABOUT_ME,
)) + r')(?: (?:por favor|porfa|gracias|obrigad[oa]|please|thanks|ya|agora|ahora))*$')
_FORGET = re.compile(_PLEASE + '(?:' + '|'.join((
    rf'{_FORGET_VERB} \w+',
    r'(?:deja|deje) de recordar \w+', r'(?:ya )?no recuerdes \w+', r'(?:ya )?no (?:guardes|uses) lo que',
    r'nao lembre(?: mais)? \w+', r'pare de lembrar \w+',
    rf'{_ERASE_VERB} (?:eso |esto |isso )?(?:de (?:tu|la) memoria|da (?:sua )?memoria)',
    rf'{_ERASE_VERB} (?:lo que (?:te|le) (?:dije|conte)|o que eu (?:te )?(?:disse|falei|contei))',
    rf'{_APAGA} (?:isso )?(?:da (?:sua )?memoria|o que eu (?:te )?(?:disse|falei|contei))',
    # A list or a draft, as likely as memory: the model reads which.
    rf'{_ERASE_VERB} (?:todo|tudo) lo anterior',
)) + r')')
# An erase verb, or a forget, that belongs to something else: a password, a rule, an alert, the account.
_NOT_MEMORY = _any(r'contrasena', r'clave', r'senha', r'password', r'pin', r'reglas?', r'regras?', r'alertas?',
                   r'objetivo de (?:inversion|reparto)', r'movimientos?', r'clasificacion')
# Something they told us: forgetting it is memory's, whatever it was (a password most of all).
_TOLD = _any(r'(?:que|lo que) (?:te|le) (?:dije|di|conte|pase|escribi|mande|envie)',
             r'que eu (?:te )?(?:disse|dei|contei|passei|falei|escrevi|mandei|enviei)',
             r'o que eu (?:te )?(?:disse|dei|contei|passei|falei|escrevi|mandei|enviei)',
             r'that i (?:told|gave|sent)')
_NO_PAUSE = re.compile(r'^[¡!¿\s]*(?:no|nao|si|sim|dale|claro|perfecto)\s*[,.;:!]+\s*')


def command(text) -> str:
    """'remember' | 'forget' | 'wipe' | '': is this message, taken whole, the
    person asking about their memory? A cue: for the first two a model with no
    tools then says what is meant, from the closed lists."""
    raw = str(text or '').strip()
    if not raw or len(raw) > COMMAND_MAX_CHARS or '\n' in raw:
        return ''  # a paste is never a request about memory
    # "no, olvida eso" is not "no olvides eso", nor "si olvido…" "sí, olvida…": only with a pause after it.
    paused = _NO_PAUSE.match(fold(raw))
    plain = words_of(_NO_PAUSE.sub('', fold(raw)))
    # After a "no" it may be "never mind": never deleted unread.
    refused = paused and paused.group().lstrip('¡!¿ ').startswith(('no', 'nao'))
    if '?' not in raw and _WIPE.match(plain):
        return 'forget' if refused else 'wipe'
    if _FORGET.match(plain):
        theirs = _TOLD.search(plain) or SENSITIVE.search(plain)
        return 'forget' if theirs or not _NOT_MEMORY.search(plain) else ''
    return 'remember' if _REMEMBER.match(plain) else ''


def valid(kind, value) -> str:
    """The value as it is stored, '' when it is not on the list."""
    return value if isinstance(value, str) and value in VALUES.get(kind, {}) else ''


def label(kind, value) -> str:
    return VALUES.get(kind, {}).get(value, '') if isinstance(value, str) else ''
