# Yith Library Server is a password storage server.
# Copyright (C) 2012-2013 Yaco Sistemas
# Copyright (C) 2012-2013 Alejandro Blanco Escudero <alejandro.b.e@gmail.com>
# Copyright (C) 2012-2013 Lorenzo Gil Sanchez <lorenzo.gil.sanchez@gmail.com>
#
# This file is part of Yith Library Server.
#
# Yith Library Server is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Yith Library Server is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Yith Library Server.  If not, see <http://www.gnu.org/licenses/>.

import os

import bson

from yithlibraryserver import testing
from yithlibraryserver.compat import encodebytes, encode_header, urlparse
from yithlibraryserver.oauth2.authorization import Authorizator


def auth_basic_encode(user, password):
    value = '%s:%s' % (user, password)
    value = 'Basic ' + encodebytes(value.encode('utf-8')).decode('utf-8')
    return encode_header(value)


class AuthorizationEndpointTests(testing.TestCase):

    clean_collections = ('applications', 'users', 'authorization_codes')

    def test_anonymous_user(self):
        # this view requires authentication
        res = self.testapp.get('/oauth2/endpoints/authorization')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Log in')

    def _login(self):
        user_id = self.db.users.insert({
                'twitter_id': 'twitter1',
                'screen_name': 'John Doe',
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'john@example.com',
                'authorized_apps': [],
                })
        self.testapp.get('/__login/' + str(user_id))
        return user_id

    def _create_client(self):
        owner_id = self.db.users.insert({
                'twitter_id': 'twitter2',
                'screen_name': 'Administrator',
                'first_name': 'Alice',
                'last_name': 'Doe',
                'email': 'alice@example.com',
                })
        app_id = self.db.applications.insert({
                'owner': owner_id,
                'client_id': '123456',
                'name': 'Example',
                'main_url': 'https://example.com',
                'callback_url': 'https://example.com/callback',
                'image_url': 'https://example.com/logo.png',
                'description': 'Example description',
                })
        return owner_id, app_id

    def test_no_client_id(self):
        self._login()
        res = self.testapp.get('/oauth2/endpoints/authorization',
                               status=400)
        self.assertEqual(res.status, '400 Bad Request')
        res.mustcontain('Error is: invalid_client_id')

    def test_invalid_client_id(self):
        self._login()
        res = self.testapp.get('/oauth2/endpoints/authorization', {
            'client_id': '1234',
        }, status=400)
        self.assertEqual(res.status, '400 Bad Request')
        res.mustcontain('Error is: invalid_client_id')

    def _assert_error(self, url, error, description=None):
        query = urlparse.parse_qs(urlparse.urlparse(url).query)
        expected = {'error': [error]}
        if description:
            expected['error_description'] = [description]

        self.assertEqual(query, expected)

    def test_no_response_type(self):
        self._login()
        self._create_client()
        res = self.testapp.get('/oauth2/endpoints/authorization', {
            'client_id': '123456',
        }, status=302)
        self.assertEqual(res.status, '302 Found')
        self._assert_error(res.location, 'invalid_request',
                           'Missing response_type parameter.')

    def test_invalid_redirect_callback(self):
        self._login()
        self._create_client()
        res = self.testapp.get('/oauth2/endpoints/authorization', {
            'client_id': '123456',
            'response_type': 'code',
            'redirect_uri': 'https://example.com/bad-callback',
        }, status=400)
        self.assertEqual(res.status, '400 Bad Request')
        res.mustcontain('Error is: mismatching_redirect_uri')

    def test_user_cancel(self):
        self._login()
        self._create_client()
        res = self.testapp.get('/oauth2/endpoints/authorization', {
            'client_id': '123456',
            'response_type': 'code',
            'redirect_uri': 'https://example.com/callback',
        })
        self.assertEqual(res.status, '200 OK')

        res = self.testapp.post('/oauth2/endpoints/authorization', {
            'cancel': 'No thanks',
            'response_type': 'code',
            'client_id': '123456',
            'redirect_uri': 'https://example.com/callback',
            'scope': 'read-passwords',
        })
        self.assertEqual(res.status, '302 Found')
        self.assertEqual(res.location,
                         'https://example.com/callback?error=access_denied')

    def test_non_authorized_app_yet(self):
        os.environ['YITH_FAKE_DATETIME'] = '2012-1-10-15-31-11'

        user_id = self._login()
        self._create_client()

        authorizator = Authorizator(self.db)
        auths = authorizator.get_user_authorizations({'_id': user_id})
        self.assertEqual(auths.count(), 0)

        res = self.testapp.get('/oauth2/endpoints/authorization', {
            'response_type': 'code',
            'client_id': '123456',
            'redirect_uri': 'https://example.com/callback',
        })
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('is asking your permission for')
        res.mustcontain('Allow access')
        res.mustcontain('No, thanks')

        res = self.testapp.post('/oauth2/endpoints/authorization', {
            'submit': 'Authorize',
            'response_type': 'code',
            'client_id': '123456',
            'redirect_uri': 'https://example.com/callback',
            'scope': 'read-passwords',
        })
        self.assertEqual(res.status, '302 Found')

        # Check that the app is authorized now
        auths = authorizator.get_user_authorizations({'_id': user_id})
        self.assertEqual(auths.count(), 1)
        auth = auths[0]
        self.assertEqual(auth['redirect_uri'], 'https://example.com/callback')
        self.assertEqual(auth['response_type'], 'code')
        self.assertEqual(auth['client_id'], '123456')
        self.assertEqual(auth['scope'], 'read-passwords')
        self.assertEqual(auth['user'], user_id)

        # Check the right redirect url
        grant = self.db.authorization_codes.find_one({
            'client_id': '123456',
            'user': user_id,
        })
        self.assertNotEqual(grant, None)
        code = grant['code']
        location = 'https://example.com/callback?code=%s' % code
        self.assertEqual(res.location, location)

        del os.environ['YITH_FAKE_DATETIME']

    def test_already_authorized_app(self):
        os.environ['YITH_FAKE_DATETIME'] = '2012-1-10-15-31-11'

        user_id = self._login()
        self._create_client()

        authorizator = Authorizator(self.db)
        auths = authorizator.get_user_authorizations({'_id': user_id})
        self.assertEqual(auths.count(), 0)

        # do an initial authorization
        res = self.testapp.get('/oauth2/endpoints/authorization', {
            'response_type': 'code',
            'client_id': '123456',
            'redirect_uri': 'https://example.com/callback',
        })
        self.assertEqual(res.status, '200 OK')

        res = self.testapp.post('/oauth2/endpoints/authorization', {
            'submit': 'Authorize',
            'response_type': 'code',
            'client_id': '123456',
            'redirect_uri': 'https://example.com/callback',
            'scope': 'read-passwords',
        })
        self.assertEqual(res.status, '302 Found')

        auths = authorizator.get_user_authorizations({'_id': user_id})
        self.assertEqual(auths.count(), 1)

        # Now do a second authorization
        res = self.testapp.get('/oauth2/endpoints/authorization', {
            'response_type': 'code',
            'client_id': '123456',
            'redirect_uri': 'https://example.com/callback',
        })
        self.assertEqual(res.status, '302 Found')

        auths = authorizator.get_user_authorizations({'_id': user_id})
        self.assertEqual(auths.count(), 1)

        grants = self.db.authorization_codes.find({
            'client_id': '123456',
            'user': user_id,
        })

        # There are two grants now
        self.assertEqual(grants.count(), 2)
        code = grants[1]['code']
        location = 'https://example.com/callback?code=%s' % code
        self.assertEqual(res.location, location)

        del os.environ['YITH_FAKE_DATETIME']


class ViewTests(object):

    clean_collections = ('applications', 'users', 'authorization_codes',
                         'access_codes')

    def test_token_endpoint(self):
        # 1. test incorrect requests
        res = self.testapp.post('/oauth2/endpoints/token', {}, status=401)
        self.assertEqual(res.status, '401 Unauthorized')

        headers = {
            'Authorization': auth_basic_encode('123456', 'secret'),
            }

        res = self.testapp.post('/oauth2/endpoints/token', {}, headers=headers, status=401)
        self.assertEqual(res.status, '401 Unauthorized')

        app_id = self.db.applications.insert({
                'client_id': '123456',
                'client_secret': 'secret',
                'callback_url': 'https://example.com/callback',
                'name': 'Example',
                'main_url': 'https://example.com',
                })

        res = self.testapp.post('/oauth2/endpoints/token', {}, headers=headers, status=400)
        self.assertEqual(res.status, '400 Bad Request')
        res.mustcontain('Missing required grant_type')

        res = self.testapp.post('/oauth2/endpoints/token', {
                'grant_type': 'password'
                }, headers=headers, status=501)
        self.assertEqual(res.status, '501 Not Implemented')
        res.mustcontain('Only authorization_code is supported')

        res = self.testapp.post('/oauth2/endpoints/token', {
                'grant_type': 'authorization_code',
                }, headers=headers, status=400)
        self.assertEqual(res.status, '400 Bad Request')
        res.mustcontain('Missing required code')

        res = self.testapp.post('/oauth2/endpoints/token', {
                'grant_type': 'authorization_code',
                'code': 'this-code-does-not-exist',
                }, headers=headers, status=401)
        self.assertEqual(res.status, '401 Unauthorized')

        # 2. Test a valid request

        # first we generate an authorization_code
        user_id = self.db.users.insert({
                'twitter_id': 'twitter1',
                'screen_name': 'John Doe',
                'first_name': 'John',
                'last_name': 'Doe',
                'authorized_apps': [app_id],
                })
        self.testapp.get('/__login/' + str(user_id))

        res = self.testapp.get('/oauth2/endpoints/authorization', {
                'response_type': 'code',
                'client_id': '123456',
                'redirect_uri': 'https://example.com/callback',
                })
        self.assertEqual(res.status, '302 Found')
        grant = self.db.authorization_codes.find_one({
                'client_id': '123456',
                'user': user_id,
                })
        self.assertNotEqual(grant, None)
        code = grant['code']

        # now send the token request
        res = self.testapp.post('/oauth2/endpoints/token', {
                'grant_type': 'authorization_code',
                'code': code,
                }, headers=headers)
        self.assertEqual(res.status, '200 OK')
        self.assertEqual(res.headers['Cache-Control'], 'no-store')
        self.assertEqual(res.headers['Pragma'], 'no-cache')

        # the grant code should be removed
        grant = self.db.authorization_codes.find_one({
                'client_id': '123456',
                'user': user_id,
                })
        self.assertEqual(grant, None)

        # and an access token should be created
        self.assertEqual(res.json['token_type'], 'bearer')
        self.assertEqual(res.json['expires_in'], 3600)

        access_code = self.db.access_codes.find_one({
                'code': res.json['access_code'],
                })
        self.assertNotEqual(access_code, None)

    def test_token_endpoint_bad_client_id(self):
        app_id = self.db.applications.insert({
                'client_id': '123456',
                'client_secret': 'secret',
                'callback_url': 'https://example.com/callback',
                'name': 'Example',
                'main_url': 'https://example.com',
                })

        app_id2 = self.db.applications.insert({
                'client_id': '98765',
                'client_secret': 'secret2',
                'callback_url': 'https://example.com/callback2',
                'name': 'Example2',
                'main_url': 'https://example.com',
                })

        user_id = self.db.users.insert({
                'twitter_id': 'twitter1',
                'screen_name': 'John Doe',
                'first_name': 'John',
                'last_name': 'Doe',
                'authorized_apps': [app_id, app_id2],
                })
        self.testapp.get('/__login/' + str(user_id))

        self.testapp.get('/oauth2/endpoints/authorization', {
                'response_type': 'code',
                'client_id': '123456',
                })
        grant = self.db.authorization_codes.find_one({
                'client_id': '123456',
                'user': user_id,
                })
        code = grant['code']

        # Authorize with app2 credentials
        headers = {
            'Authorization': auth_basic_encode('98765', 'secret2'),
            }
        res = self.testapp.post('/oauth2/endpoints/token', {
                'grant_type': 'authorization_code',
                'code': code,
                }, headers=headers, status=401)
        self.assertEqual(res.status, '401 Unauthorized')

    def test_applications(self):
        # this view required authentication
        res = self.testapp.get('/oauth2/applications')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Log in')

        # Log in
        user_id = self.db.users.insert({
                'twitter_id': 'twitter1',
                'screen_name': 'John Doe',
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'john@example.com',
                'authorized_apps': [],
                })
        self.testapp.get('/__login/' + str(user_id))

        res = self.testapp.get('/oauth2/applications')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('John')
        res.mustcontain('Log out')
        res.mustcontain('Developer Applications')
        res.mustcontain('Register new application')

        # TODO: test creating apps and make sure they appear in the output

    def test_application_new(self):
        # this view required authentication
        res = self.testapp.get('/oauth2/applications/new')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Log in')

        # Log in
        user_id = self.db.users.insert({
                'twitter_id': 'twitter1',
                'screen_name': 'John Doe',
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'john@example.com',
                'authorized_apps': [],
                })
        self.testapp.get('/__login/' + str(user_id))

        res = self.testapp.get('/oauth2/applications/new')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('New Application')
        res.mustcontain('Name')
        res.mustcontain('Main URL')
        res.mustcontain('Callback URL')
        res.mustcontain('Authorized Origins')
        res.mustcontain('Production ready')
        res.mustcontain('Image URL')
        res.mustcontain('Description')

        res = self.testapp.post('/oauth2/applications/new', {
                'name': 'Test Application',
                'main_url': 'http://example.com',
                'callback_url': 'http://example.com/callback',
                'authorized_origins': '''http://example.com
https://example.com''',
                'submit': 'submit',
                })
        self.assertEqual(res.status, '302 Found')
        self.assertEqual(res.location, 'http://localhost/oauth2/applications')

        app = self.db.applications.find_one({
                'name': 'Test Application',
                'main_url': 'http://example.com',
                'callback_url': 'http://example.com/callback',
                'authorized_origins': ['http://example.com',
                                       'https://example.com'],
                })
        self.assertNotEqual(app, None)
        self.assertTrue('client_id' in app)
        self.assertTrue('client_secret' in app)
        self.assertEqual(app['owner'], user_id)
        self.assertEqual(app['name'], 'Test Application')
        self.assertEqual(app['main_url'], 'http://example.com')
        self.assertEqual(app['callback_url'], 'http://example.com/callback')
        self.assertEqual(app['authorized_origins'],
                         ['http://example.com', 'https://example.com'])
        self.assertEqual(app['production_ready'], False)
        self.assertEqual(app['image_url'], '')
        self.assertEqual(app['description'], '')

        # error if we don't fill all fields
        res = self.testapp.post('/oauth2/applications/new', {
                'name': 'Test Application',
                'callback_url': 'http://example.com/callback',
                'submit': 'submit',
                })
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('There was a problem with your submission')

        # The user hit the cancel button
        res = self.testapp.post('/oauth2/applications/new', {
                'cancel': 'Cancel',
                })
        self.assertEqual(res.status, '302 Found')
        self.assertEqual(res.location, 'http://localhost/oauth2/applications')

    def test_application_delete(self):
        # this view required authentication
        res = self.testapp.get('/oauth2/applications/new')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Log in')

        # Log in
        user_id = self.db.users.insert({
                'twitter_id': 'twitter1',
                'screen_name': 'John Doe',
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'john@example.com',
                'authorized_apps': [],
                })
        self.testapp.get('/__login/' + str(user_id))

        res = self.testapp.get('/oauth2/applications/xxx/delete',
                               status=400)
        self.assertEqual(res.status, '400 Bad Request')
        res.mustcontain('Invalid application id')

        res = self.testapp.get('/oauth2/applications/000000000000000000000000/delete',
                               status=404)
        self.assertEqual(res.status, '404 Not Found')

        # create a valid app
        app_id = self.db.applications.insert({
                'owner': bson.ObjectId(),
                'name': 'Test Application',
                'client_id': '123456',
                'callback_url': 'https://example.com/callback',
                'production_ready': False,
                })

        res = self.testapp.get('/oauth2/applications/%s/delete' % str(app_id),
                               status=401)
        self.assertEqual(res.status, '401 Unauthorized')

        self.db.applications.update({'_id': app_id}, {
                '$set': {'owner': user_id},
                })
        res = self.testapp.get('/oauth2/applications/%s/delete' % str(app_id))
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Delete Application <span>Test Application</span>')
        res.mustcontain('Are you sure you want to remove the application')
        res.mustcontain('Yes, I am sure')
        res.mustcontain('No, take me back to the application list')

        # now delete it
        res = self.testapp.post('/oauth2/applications/%s/delete' % str(app_id),
                                {'submit': 'Yes, I am sure'})
        self.assertEqual(res.status, '302 Found')
        self.assertEqual(res.location, 'http://localhost/oauth2/applications')

        app = self.db.applications.find_one(app_id)
        self.assertEqual(app, None)

    def test_application_edit(self):
        # this view required authentication
        res = self.testapp.get('/oauth2/applications/xxx/edit')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Log in')

        # Log in
        user_id = self.db.users.insert({
                'twitter_id': 'twitter1',
                'screen_name': 'John Doe',
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'john@example.com',
                'authorized_apps': [],
                })
        self.testapp.get('/__login/' + str(user_id))

        res = self.testapp.get('/oauth2/applications/xxx/edit',
                               status=400)
        self.assertEqual(res.status, '400 Bad Request')
        res.mustcontain('Invalid application id')

        res = self.testapp.get(
            '/oauth2/applications/000000000000000000000000/edit',
            status=404)
        self.assertEqual(res.status, '404 Not Found')

        # create a valid app
        app_id = self.db.applications.insert({
                'owner': bson.ObjectId(),
                'name': 'Test Application',
                'main_url': 'http://example.com',
                'callback_url': 'http://example.com/callback',
                'authorized_origins': ['http://example.com',
                                       'https://example.com'],
                'production_ready': False,
                'image_url': 'http://example.com/image.png',
                'description': 'example description',
                'client_id': '123456',
                'client_secret': 'secret',
                })

        res = self.testapp.get('/oauth2/applications/%s/edit' % str(app_id),
                               status=401)
        self.assertEqual(res.status, '401 Unauthorized')

        self.db.applications.update({'_id': app_id}, {
                '$set': {'owner': user_id},
                })
        res = self.testapp.get('/oauth2/applications/%s/edit' % str(app_id))
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Edit application <span>Test Application</span>')
        res.mustcontain('Name')
        res.mustcontain('Test Application')
        res.mustcontain('Main URL')
        res.mustcontain('http://example.com')
        res.mustcontain('Callback URL')
        res.mustcontain('http://example.com/callback')
        res.mustcontain('Authorized Origins')
        res.mustcontain("""http://example.com
https://example.com""")
        res.mustcontain('Production ready')
        res.mustcontain('Image URL')
        res.mustcontain('http://example.com/image.png')
        res.mustcontain('Description')
        res.mustcontain('example description')
        res.mustcontain('Client Id')
        res.mustcontain('123456')
        res.mustcontain('Client secret')
        res.mustcontain('secret')
        res.mustcontain('Save application')
        res.mustcontain('Delete application')
        res.mustcontain('Cancel')

        # Let's make some changes
        old_count = self.db.applications.count()
        res = self.testapp.post('/oauth2/applications/%s/edit' % str(app_id), {
                'name': 'Test Application 2',
                'main_url': 'http://example.com/new',
                'callback_url': 'http://example.com/new/callback',
                'authorized_origins': 'http://client.example.com',
                'production_ready': 'true',
                'image_url': 'http://example.com/image2.png',
                'description': 'example description 2',
                'client_id': '123456-2',
                'client_secret': 'secret2',
                'submit': 'Save changes',
                })
        self.assertEqual(res.status, '302 Found')
        self.assertEqual(res.location, 'http://localhost/oauth2/applications')
        new_app = self.db.applications.find_one(app_id)
        self.assertEqual(new_app['name'], 'Test Application 2')
        self.assertEqual(new_app['main_url'],
                         'http://example.com/new')
        self.assertEqual(new_app['callback_url'],
                         'http://example.com/new/callback')
        self.assertEqual(new_app['authorized_origins'],
                         ['http://client.example.com'])
        self.assertEqual(new_app['production_ready'], True)
        self.assertEqual(new_app['image_url'], 'http://example.com/image2.png')
        self.assertEqual(new_app['description'], 'example description 2')
        # the Id and Secret shouldn't change
        self.assertEqual(new_app['client_id'], '123456')
        self.assertEqual(new_app['client_secret'], 'secret')
        self.assertEqual(old_count, self.db.applications.count())

        # Try and invalid change
        res = self.testapp.post('/oauth2/applications/%s/edit' % str(app_id), {
                'submit': 'Save changes',
                })
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('There was a problem with your submission')
        res.mustcontain('Required')

        # The user hit the delete button
        res = self.testapp.post('/oauth2/applications/%s/edit' % str(app_id), {
                'delete': 'Delete',
                })
        self.assertEqual(res.status, '302 Found')
        self.assertEqual(res.location,
                         'http://localhost/oauth2/applications/%s/delete'
                         % str(app_id))

        # The user hit the cancel button
        res = self.testapp.post('/oauth2/applications/%s/edit' % str(app_id), {
                'cancel': 'Cancel',
                })
        self.assertEqual(res.status, '302 Found')
        self.assertEqual(res.location, 'http://localhost/oauth2/applications')

    def test_authorized_applications(self):
        # this view required authentication
        res = self.testapp.get('/oauth2/authorized-applications')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Log in')

        # Log in
        user_id = self.db.users.insert({
                'twitter_id': 'twitter1',
                'screen_name': 'John Doe',
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'john@example.com',
                'authorized_apps': [],
                })
        self.testapp.get('/__login/' + str(user_id))

        res = self.testapp.get('/oauth2/authorized-applications')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Authorized Applications')

    def test_revoke_application(self):
        # this view required authentication
        res = self.testapp.get('/oauth2/applications/xxx/revoke')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Log in')

        # Log in
        user_id = self.db.users.insert({
                'twitter_id': 'twitter1',
                'screen_name': 'John Doe',
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'john@example.com',
                'authorized_apps': [],
                })
        self.testapp.get('/__login/' + str(user_id))

        res = self.testapp.get('/oauth2/applications/xxx/revoke',
                               status=400)
        self.assertEqual(res.status, '400 Bad Request')
        res.mustcontain('Invalid application id')

        res = self.testapp.get(
            '/oauth2/applications/000000000000000000000000/revoke',
            status=404)
        self.assertEqual(res.status, '404 Not Found')

        # create a valid app
        app_id = self.db.applications.insert({
                'owner': bson.ObjectId(),
                'name': 'Test Application',
                'main_url': 'http://example.com',
                'callback_url': 'http://example.com/callback',
                'client_id': '123456',
                'client_secret': 'secret',
                })

        res = self.testapp.get('/oauth2/applications/%s/revoke' % str(app_id),
                               status=401)
        self.assertEqual(res.status, '401 Unauthorized')

        self.db.users.update({'_id': user_id}, {
                '$set': {'authorized_apps': [app_id]},
                })

        res = self.testapp.get('/oauth2/applications/%s/revoke' % str(app_id))
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Revoke authorization to application <span>Test Application</span>')

        res = self.testapp.post('/oauth2/applications/%s/revoke' % str(app_id), {
                'submit': 'Yes, I am sure',
                })
        self.assertEqual(res.status, '302 Found')
        self.assertEqual(res.location, 'http://localhost/oauth2/authorized-applications')
        user = self.db.users.find_one(user_id)
        self.assertEqual(user['authorized_apps'], [])

    def test_clients(self):
        res = self.testapp.get('/oauth2/clients')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain('Available Clients')

        # create a couple of apps
        self.db.applications.insert({
                'client_id': '123456',
                'name': 'Example app 1',
                'main_url': 'https://example.com',
                'callback_url': 'https://example.com/callback',
                'production_ready': True,
                'image_url': 'https://example.com/image.png',
                'description': 'example description',
                })
        self.db.applications.insert({
                'client_id': '654321',
                'name': 'Example app 2',
                'main_url': 'https://2.example.com',
                'callback_url': 'https://2.example.com/callback',
                'production_ready': False,
                })

        res = self.testapp.get('/oauth2/clients')
        self.assertEqual(res.status, '200 OK')
        res.mustcontain(
            'Available Clients', 'Example app 1', 'https://example.com',
            'https://example.com/image.png', 'example description',
            no=('Example app 2', 'https://2.example.com'),
            )

