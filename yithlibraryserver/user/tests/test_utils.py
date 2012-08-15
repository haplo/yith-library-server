import unittest

from pyramid import testing

from yithlibraryserver.db import MongoDB
from yithlibraryserver.testing import MONGO_URI

from yithlibraryserver.user.utils import split_name, update_user


class UtilsTests(unittest.TestCase):

    def setUp(self):
        self.config = testing.setUp()
        self.config.include('yithlibraryserver.user')
        mdb = MongoDB(MONGO_URI)
        self.db = mdb.get_database()

    def tearDown(self):
        testing.tearDown()
        self.db.drop_collection('users')

    def test_split_name(self):
        self.assertEquals(split_name('John Doe'),
                          ('John', 'Doe'))
        self.assertEquals(split_name('John'),
                          ('John', ''))
        self.assertEquals(split_name('John M Doe'),
                          ('John', 'M Doe'))
        self.assertEquals(split_name(''),
                          ('', ''))

    def test_update_user(self):
        user_id = self.db.users.insert({
                'screen_name': 'John Doe',
                'first_name': 'John',
                'last_name': '',
                }, safe=True)
        user = self.db.users.find_one({'_id': user_id})
        update_user(self.db, user, {})

        updated_user = self.db.users.find_one({'_id': user_id})
        # the user has not changed
        self.assertEqual(updated_user['screen_name'], user['screen_name'])
        self.assertEqual(updated_user['first_name'], user['first_name'])
        self.assertEqual(updated_user['last_name'], user['last_name'])

        # update the last_name
        update_user(self.db, user, {'last_name': 'Doe'})
        updated_user = self.db.users.find_one({'_id': user_id})
        self.assertEqual(updated_user['last_name'], 'Doe')

        # add an email attribute
        update_user(self.db, user, {'email': 'john@example.com'})
        updated_user = self.db.users.find_one({'_id': user_id})
        self.assertEqual(updated_user['email'], 'john@example.com')

        # if an attribute has no value, no update happens
        update_user(self.db, user, {'first_name': ''})
        updated_user = self.db.users.find_one({'_id': user_id})
        self.assertEqual(updated_user['first_name'], 'John')