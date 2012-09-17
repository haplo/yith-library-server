# Yith Library Server is a password storage server.
# Copyright (C) 2012 Yaco Sistemas
# Copyright (C) 2012 Alejandro Blanco Escudero <alejandro.b.e@gmail.com>
# Copyright (C) 2012 Lorenzo Gil Sanchez <lorenzo.gil.sanchez@gmail.com>
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

from mock import patch

from openid.association import Association
from openid.consumer.consumer import AuthRequest
from openid.consumer.consumer import SUCCESS, CANCEL, FAILURE, SETUP_NEEDED
from openid.consumer.discover import OpenIDServiceEndpoint

from yithlibraryserver import testing
from yithlibraryserver.compat import urlparse


XRDS = '<?xml version="1.0" encoding="UTF-8"?>\n<xrds:XRDS xmlns:xrds="xri://$xrds" xmlns="xri://$xrd*($v*2.0)">\n<XRD>\n<Service priority="0">\n<Type>http://specs.openid.net/auth/2.0/server</Type>\n<Type>http://openid.net/srv/ax/1.0</Type>\n<Type>http://specs.openid.net/extensions/ui/1.0/mode/popup</Type>\n<Type>http://specs.openid.net/extensions/ui/1.0/icon</Type>\n<Type>http://specs.openid.net/extensions/pape/1.0</Type>\n<URI>https://www.google.com/accounts/o8/ud</URI>\n</Service>\n</XRD>\n</xrds:XRDS>\n'

ASSOC_HANDLE = 'AMlYA9W_FbThybIcK6l0Wdl95D11KtOA3zDpTU8juWzgKMY-xlqf3bh0'


def get_association():
    secret = '\xe1\xee\xae>n|\xaa*="Elq\x1c"n\xe4u3\xbf'
    issued = 1346478836
    lifetime = 46799
    assoc_type = 'HMAC-SHA1'
    return Association(ASSOC_HANDLE, secret, issued, lifetime, assoc_type)


class DummyInfo(object):

    def __init__(self, status, identifier=None, response=None):
        self.status = status
        self.identifier = identifier
        self.response = response

    def getDisplayIdentifier(self):
        return self.identifier

    def extensionResponse(self, uri, signed):
        return self.response


class ViewTests(testing.TestCase):

    clean_collections = ('users', )

    def test_google_login(self):
        with patch('openid.consumer.consumer.Consumer.begin') as fake:
            # we don't want to hit the wire in the tests
            # so we avoid the discovery and association handle
            # steps with this code
            endpoints = OpenIDServiceEndpoint.fromXRDS(
                'https://www.google.com/accounts/o8/ud',
                XRDS,
                )
            association = get_association()
            auth_req = AuthRequest(endpoints[0], association)
            auth_req.setAnonymous(False)
            fake.return_value = auth_req

            res = self.testapp.get('/google/login', {
                    'next_url': 'https://localhost/foo/bar',
                    })
            self.assertEqual(res.status, '302 Found')
            url = urlparse.urlparse(res.location)
            self.assertEqual(url.netloc, 'www.google.com')
            self.assertEqual(url.path, '/accounts/o8/ud')
            query = urlparse.parse_qs(url.query)
            self.assertEqual(tuple(query.keys()),
                             ('openid.ns', 'openid.realm', 'openid.return_to',
                              'openid.ax.mode', 'openid.claimed_id', 'openid.mode',
                              'openid.ns.ax', 'openid.identity', 'openid.assoc_handle',
                              'openid.ax.required', 'openid.ax.type.ext0', 'openid.ax.type.ext1', 'openid.ax.type.ext2'))
            self.assertEqual(query['openid.ns'],
                             ['http://specs.openid.net/auth/2.0'])
            self.assertEqual(query['openid.realm'],
                             ['http://localhost/'])
            self.assertEqual(query['openid.return_to'],
                             ['http://localhost/google/callback'])
            self.assertEqual(query['openid.ax.mode'], ['fetch_request'])
            self.assertEqual(query['openid.claimed_id'],
                             ['http://specs.openid.net/auth/2.0/identifier_select'])
            self.assertEqual(query['openid.mode'], ['checkid_setup'])
            self.assertEqual(query['openid.ns.ax'],
                             ['http://openid.net/srv/ax/1.0'])
            self.assertEqual(query['openid.identity'],
                             ['http://specs.openid.net/auth/2.0/identifier_select'])
            self.assertEqual(query['openid.assoc_handle'], [ASSOC_HANDLE])
            self.assertEqual(query['openid.ax.required'], ['ext0,ext1,ext2'])
            self.assertEqual(query['openid.ax.type.ext0'],
                             ['http://axschema.org/namePerson/first'])
            self.assertEqual(query['openid.ax.type.ext1'],
                             ['http://axschema.org/namePerson/last'])
            self.assertEqual(query['openid.ax.type.ext2'],
                             ['http://axschema.org/contact/email'])

    def test_google_callback(self):

        with patch('openid.consumer.consumer.Consumer.complete') as fake:
            fake.return_value = DummyInfo(CANCEL)
            res = self.testapp.get('/google/callback')
            self.assertEqual(res.text, 'canceled')

            fake.return_value = DummyInfo(FAILURE)
            res = self.testapp.get('/google/callback')
            self.assertEqual(res.text, 'failure')

            fake.return_value = DummyInfo(SETUP_NEEDED)
            res = self.testapp.get('/google/callback')
            self.assertEqual(res.text, 'setup needed')

            fake.return_value = DummyInfo('other')
            res = self.testapp.get('/google/callback')
            self.assertEqual(res.text, 'unknown failure')

            fake.return_value = DummyInfo(
                SUCCESS,
                'https://www.google.com/accounts/o8/id?id=1234',
                {'value.ext2': 'john@example.com',
                 'value.ext0': 'John',
                 'value.ext1': 'Doe',
                 'type.ext0': 'http://axschema.org/namePerson/first',
                 'type.ext1': 'http://axschema.org/namePerson/last',
                 'type.ext2': 'http://axschema.org/contact/email',
                 'mode': 'fetch_response'}
                )
            res = self.testapp.get('/google/callback')
            self.assertEqual(res.status, '302 Found')
            self.assertEqual(res.location, 'http://localhost/register')

            # do the same login but with an existing user
            self.db.users.insert({
                    'google_id': '1234',
                    'first_name': 'John',
                    'last_name': 'Doe',
                    }, safe=True)

            fake.return_value = DummyInfo(
                SUCCESS,
                'https://www.google.com/accounts/o8/id?id=1234',
                {'value.ext2': 'john@example.com',
                 'value.ext0': 'John',
                 'value.ext1': 'Doe',
                 'type.ext0': 'http://axschema.org/namePerson/first',
                 'type.ext1': 'http://axschema.org/namePerson/last',
                 'type.ext2': 'http://axschema.org/contact/email',
                 'mode': 'fetch_response'}
                )
            res = self.testapp.get('/google/callback')
            self.assertEqual(res.status, '302 Found')
            self.assertEqual(res.location, 'http://localhost/')
            self.assertTrue('Set-Cookie' in res.headers)