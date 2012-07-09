import json


def validate_password(rawdata, encoding):
    errors = []

    try:
        data = json.loads(rawdata.decode(encoding))
    except TypeError:
        errors.append('Not valid JSON')
        return {}, errors  # this is a non recoverable error

    password = {}

    # TODO: check the _id

    # white list submission attributes ignoring anything else
    # first required attributes
    try:
        password['secret'] = data['secret']
    except KeyError:
        errors.append('Secret is required')

    try:
        password['service'] = data['service']
    except KeyError:
        errors.append('Service is required')

    # then optional attributes
    password['account'] = data.get('account')
    password['expiration'] = data.get('expiration')
    password['notes'] = data.get('notes')
    password['tags'] = data.get('tags')

    return password, errors
