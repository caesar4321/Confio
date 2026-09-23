from graphql import GraphQLError


def validate_poll_metadata(metadata, previous=None, has_votes=False):
    if not isinstance(metadata, dict):
        raise GraphQLError('Metadata debe ser un objeto JSON')
    poll = metadata.get('poll')
    if poll is not None:
        if not isinstance(poll, dict):
            raise GraphQLError('Encuesta inválida')
        question = poll.get('question')
        options = poll.get('options')
        if not isinstance(question, str) or not question.strip() or len(question) > 255:
            raise GraphQLError('La pregunta debe tener entre 1 y 255 caracteres')
        if not isinstance(options, list) or not 2 <= len(options) <= 10:
            raise GraphQLError('La encuesta debe tener entre 2 y 10 opciones')
        ids, labels = set(), set()
        for option in options:
            if not isinstance(option, dict):
                raise GraphQLError('Opción inválida')
            key, label = option.get('id'), option.get('label')
            if not isinstance(key, str) or not key.strip() or len(key) > 64 or key in ids:
                raise GraphQLError('Cada opción debe tener un identificador único')
            if not isinstance(label, str) or not label.strip() or len(label) > 200 or label.strip().casefold() in labels:
                raise GraphQLError('Las opciones deben ser distintas y tener entre 1 y 200 caracteres')
            ids.add(key)
            labels.add(label.strip().casefold())
        if not isinstance(poll.get('closed', False), bool):
            raise GraphQLError('El estado de la encuesta debe ser booleano')
    old_poll = (previous or {}).get('poll')
    if has_votes and (not poll or not old_poll or
                      poll.get('question') != old_poll.get('question') or
                      poll.get('options') != old_poll.get('options')):
        raise GraphQLError('No puedes cambiar la pregunta ni las opciones después del primer voto. Puedes cerrar la encuesta.')
