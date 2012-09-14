from deform import Button, Form, ValidationFailure

from pyramid.httpexceptions import HTTPBadRequest, HTTPFound
from pyramid.security import remember, forget
from pyramid.view import view_config, forbidden_view_config

from yithlibraryserver.compat import url_quote
from yithlibraryserver.user.accounts import get_accounts, merge_accounts
from yithlibraryserver.user.email_verification import EmailVerificationCode
from yithlibraryserver.user.schemas import UserSchema


@view_config(route_name='login', renderer='templates/login.pt')
@forbidden_view_config(renderer='templates/login.pt')
def login(request):
    login_url = request.route_path('login')
    referrer = request.path
    if request.query_string:
        referrer += '?' + request.query_string
    if referrer == login_url:
        referrer = request.route_path('home')
    came_from = request.params.get('came_from', referrer)
    return {'next_url': url_quote(came_from)}


@view_config(route_name='register_new_user',
             renderer='templates/register.pt')
def register_new_user(request):
    try:
        user_info = request.session['user_info']
    except KeyError:
        return HTTPBadRequest('Missing user info in the session')

    try:
        next_url = request.session['next_url']
    except KeyError:
        next_url = request.route_url('home')

    schema = UserSchema()
    button1 = Button('submit', 'Register into Yith Library')
    button1.css_class = 'btn-primary'
    button2 = Button('cancel', 'Cancel')
    button2.css_class = ''

    form = Form(schema, buttons=(button1, button2))

    if 'submit' in request.POST:

        controls = request.POST.items()
        try:
            appstruct = form.validate(controls)
        except ValidationFailure as e:
            return {'form': e.render()}

        provider = user_info['provider']
        provider_key = provider + '_id'

        if (appstruct['email'] != ''
            and appstruct['email'] == user_info['email']):
            email_verified = True
        else:
            email_verified = False

        _id = request.db.users.insert({
                provider_key: user_info[provider_key],
                'screen_name': user_info.get('screen_name', ''),
                'first_name': appstruct['first_name'],
                'last_name': appstruct['last_name'],
                'email': appstruct['email'],
                'email_verified': email_verified,
                'authorized_apps': [],
                }, safe=True)

        del request.session['user_info']
        if 'next_url' in request.session:
            del request.session['next_url']

        return HTTPFound(location=next_url,
                         headers=remember(request, str(_id)))
    elif 'cancel' in request.POST:
        del request.session['user_info']
        if 'next_url' in request.session:
            del request.session['next_url']

        return HTTPFound(location=next_url)

    return {
        'form': form.render({
                'first_name': user_info.get('first_name', ''),
                'last_name': user_info.get('last_name', ''),
                'email': user_info.get('email', ''),
                }),
        }


@view_config(route_name='logout', renderer='string')
def logout(request):
    return HTTPFound(location=request.route_path('home'),
                     headers=forget(request))


@view_config(route_name='user_profile',
             renderer='templates/profile.pt',
             permission='edit-profile')
def profile(request):
    schema = UserSchema()
    button1 = Button('submit', 'Save changes')
    button1.css_class = 'btn-primary'
    button2 = Button('cancel', 'Cancel')
    button2.css_class = ''

    form = Form(schema, buttons=(button1, button2))

    context = {
        'accounts': get_accounts(request.db, request.user),
    }
    context['has_several_accounts'] = len(context['accounts']) > 1

    if 'submit' in request.POST:

        controls = request.POST.items()
        try:
            appstruct = form.validate(controls)
        except ValidationFailure as e:
            context['form'] = e.render()
            return context

        changes = {
            'first_name': appstruct['first_name'],
            'last_name': appstruct['last_name'],
            'email': appstruct['email'],
            }

        if request.user['email'] != appstruct['email']:
            changes['email_verified'] = False

        result = request.db.users.update({'_id': request.user['_id']},
                                         {'$set': changes},
                                         safe=True)

        if result['n'] == 1:
            request.session.flash('The changes were saved successfully',
                                  'success')
            return HTTPFound(location=request.route_path('user_profile'))
        else:
            request.session.flash('There were an error while saving your changes',
                                  'error')
            context['form'] = appstruct
            return context
    elif 'cancel' in request.POST:
        return HTTPFound(location=request.route_path('user_profile'))

    context['form'] = form.render(request.user)
    return context


@view_config(route_name='user_send_email_verification_code',
             renderer='json',
             permission='edit-profile')
def send_email_verification_code(request):
    if not request.user['email']:
        return {
            'status': 'bad',
            'error': 'You have not an email in your profile',
            }

    if 'submit' in request.POST:
        evc = EmailVerificationCode()
        if evc.store(request.db, request.user):
            link = request.route_url('user_verify_email')
            evc.send(request, request.user, link)
            return {'status': 'ok', 'error': None}
        else:
            return {
                'status': 'bad',
                'error': 'There were problems storing the verification code',
                }
    else:
        return {'status': 'bad', 'error': 'Not a post'}


@view_config(route_name='user_verify_email',
             renderer='templates/verify_email.pt')
def verify_email(request):
    try:
        code = request.params['code']
    except KeyError:
        return HTTPBadRequest('Missing code parameter')

    try:
        email = request.params['email']
    except KeyError:
        return HTTPBadRequest('Missing email parameter')

    evc = EmailVerificationCode(code)
    if evc.verify(request.db, email):
        request.session.flash(
            'Congratulations, your email has been successfully verified',
            'success',
            )
        evc.remove(request.db, email, True)
        return {
            'verified': True,
            }
    else:
        request.session.flash(
            'Sorry, your verification code is not correct or has expired',
            'error',
            )
        return {
            'verified': False,
            }


@view_config(route_name='user_merge_accounts',
             renderer='templates/merge_accounts.pt',
             permission='edit-profile')
def account_merging(request):
    available_accounts = get_accounts(request.db, request.user)
    if not len(available_accounts) > 1:
        return HTTPBadRequest('You do not have enough accounts to merge')

    if 'submit' in request.POST:

        accounts_to_merge = [account.replace('account-', '')
                             for account in request.POST.keys()
                             if account != 'submit']
        if len(accounts_to_merge) > 1:
            merged = merge_accounts(request.db, request.user, accounts_to_merge)
            if merged > 0:
                request.session.flash(
                    'Congratulations, %d of your accounts have been merged into the current one' % merged,
                    'success',
                    )
            else:
                request.session.flash(
                    'Sorry, your accounts were not merged',
                    'error',
                    )

        return HTTPFound(location=request.route_path('user_profile'))

    elif 'cancel' in request.POST:
        return HTTPFound(location=request.route_path('user_profile'))

    return {
        'accounts': available_accounts,
        }
