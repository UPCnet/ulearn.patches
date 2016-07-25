import os
import ldap
from ldap.filter import filter_format

ALT_LDAP_URI = os.environ.get('alt_ldap_uri', '')
ALT_LDAP_DN = os.environ.get('alt_bind_dn', '')
ALT_LDAP_PASSWORD = os.environ.get('alt_bindpasswd', '')
BASEDN = os.environ.get('alt_base_dn', '')

CA_GROUPS_QUERY = '(objectClass=groupOfNames)'
CA_USER_GROUPS_QUERY = '(&(objectClass=groupOfNames)(member=%s))'


def search_ldap_groups():
    """
        Patches ldap search on group search performed in syncaclgroups view
        in order to inject an extra filter to limit results for Credit Andorra LDAP.
    """
    conn = ldap.initialize(ALT_LDAP_URI)
    conn.simple_bind_s(ALT_LDAP_DN, ALT_LDAP_PASSWORD)
    return conn.search_s(BASEDN, ldap.SCOPE_SUBTREE, CA_GROUPS_QUERY, ['cn'])


def from_latin1(s):
    """
        Replaces LDAPUserFolder origin from_utf8 to return unicode from
        Credit Andorrap LDAP iso-8859-1 encoded strings
    """
    return s.decode('utf-8')


def getGroups(self, dn='*', attr=None, pwd=''):
    """
        returns a list of possible groups from the ldap tree
        (Used e.g. in showgroups.dtml) or, if a DN is passed
        in, all groups for that particular DN.
    """
    group_list = []
    no_show = ('Anonymous', 'Authenticated', 'Shared')
    if self._local_groups:
        if dn != '*':
            all_groups_list = self._groups_store.get(dn) or []
        else:
            all_groups_dict = {}
            zope_roles = list(self.valid_roles())
            zope_roles.extend(list(self._additional_groups))

            for role_name in zope_roles:
                if role_name not in no_show:
                    all_groups_dict[role_name] = 1

            all_groups_list = all_groups_dict.keys()

        for group in all_groups_list:
            if attr is None:
                group_list.append((group, group))
            else:
                group_list.append(group)

        group_list.sort()

    else:
        gscope = self._delegate.getScopes()[self.groups_scope]

        if dn != '*':
            group_filter = filter_format(CA_USER_GROUPS_QUERY, (dn,))
        else:
            group_filter = CA_GROUPS_QUERY

        res = self._delegate.search(
            base=self.groups_base,
            scope=gscope,
            filter=group_filter,
            attrs=['cn'],
            bind_dn='',
            bind_pwd='')

        exc = res['exception']
        if exc:
            if attr is None:
                group_list = (('', exc),)
            else:
                group_list = (exc,)
        elif res['size'] > 0:
            res_dicts = res['results']
            for i in range(res['size']):
                dn = res_dicts[i].get('dn')
                try:
                    cn = res_dicts[i]['cn'][0]
                except KeyError:    # NDS oddity
                    cn = self._delegate.explode_dn(dn, 1)[0]

                if attr is None:
                    group_list.append((cn, dn))
                elif attr == 'cn':
                    group_list.append(cn)
                elif attr == 'dn':
                    group_list.append(dn)

    return group_list

from Products.LDAPUserFolder.utils import VALID_GROUP_ATTRIBUTES
from Products.LDAPUserFolder.utils import guid2string
from Products.LDAPUserFolder.LDAPUserFolder import logger


def searchGroups(self, attrs=(), exact_match=False, **kw):
    """ Look up matching group records based on one or mmore attributes

    This method takes any passed-in search parameters and values as
    keyword arguments and will sort out invalid keys automatically. For
    now it only accepts valid ldap keys, with no translation, as there
    is currently no schema support for groups. The list of accepted
    group attributes is static for now.
    """
    groups = []
    groups_base = self.groups_base
    filt_list = []
    search_str = ''

    for (search_param, search_term) in kw.items():
        if search_param not in VALID_GROUP_ATTRIBUTES:
            continue
        if search_param == 'dn':
            groups_base = search_term

        elif search_param == 'objectGUID':
            # we can't escape the objectGUID query piece using filter_format
            # because it replaces backslashes, which we need as a result
            # of guid2string
            groups_base = self.groups_base
            guid = guid2string(search_term)

            if exact_match:
                filt_list.append('(objectGUID=%s)' % guid)
            else:
                filt_list.append('(objectGUID=*%s*)' % guid)

        else:
            # If the keyword arguments contain unknown items we will
            # simply ignore them and continue looking.
            if search_term and exact_match:
                filt_list.append(
                    filter_format(
                        '(%s=%s)',
                        (search_param, search_term)
                    )
                )
            elif search_term:
                filt_list.append(
                    filter_format(
                        '(%s=*%s*)',
                        (search_param, search_term)
                    )
                )
            else:
                filt_list.append('(%s=*)' % search_param)

    if len(filt_list) == 0:
        # We have no useful filter criteria, bail now before bringing the
        # site down with a search that is overly broad.
        res = {'exception': 'No useful filter criteria given'}
        res['size'] = 0

    else:
        oc_filt = CA_GROUPS_QUERY
        filt_list.append(oc_filt)
        search_str = '(&%s)' % ''.join(filt_list)
        res = self._delegate.search(
            base=groups_base,
            scope=self.groups_scope,
            filter=search_str,
            attrs=attrs,
        )

    if res['exception']:
        logger.warn('searchGroups Exception (%s)' % res['exception'])
        msg = 'searchGroups searched "%s"' % search_str
        logger.warn(msg)
        groups = [{
            'dn': res['exception'],
            'cn': 'n/a'
        }]

    elif res['size'] > 0:
        res_dicts = res['results']
        for i in range(res['size']):
            dn = res_dicts[i].get('dn')
            rec_dict = {}

            for key, val in res_dicts[i].items():
                if len(val) > 0:
                    rec_dict[key] = val[0]

            rec_dict['dn'] = dn

            groups.append(rec_dict)

    return groups

import urllib
from ZTUtils.Zope import complex_marshal


def makeQuery(self, **kw):
        return fixed_make_query(**kw)


def fixed_make_query(*args, **kwargs):
    '''Construct a URL query string, with marshalling markup.

    If there are positional arguments, they must be dictionaries.
    They are combined with the dictionary of keyword arguments to form
    a dictionary of query names and values.

    Query names (the keys) must be strings.  Values may be strings,
    integers, floats, or DateTimes, and they may also be lists or
    namespaces containing these types.  Names and string values
    should not be URL-quoted.  All arguments are marshalled with
    complex_marshal().
    '''

    d = {}
    for arg in args:
        d.update(arg)
    d.update(kwargs)

    uq = urllib.quote
    qlist = complex_marshal(d.items())
    for i in range(len(qlist)):
        k, m, v = qlist[i]
        try:
            value = str(v)
        except UnicodeEncodeError:
            value = v.encode('utf-8')

        qlist[i] = '%s%s=%s' % (uq(k), m, uq(value))

    return '&'.join(qlist)


from plone.memoize.instance import clearafter
from plone.app.workflow.browser.sharing import SharingView

original_update_role_settings = SharingView.update_role_settings


@clearafter
def update_role_settings(self, new_settings, reindex=True):
    def fix_encoding(entry):
        if not isinstance(entry['id'], unicode):
            entry['id'] = entry['id'].decode('utf-8')
        return entry
    settings = [fix_encoding(entry) for entry in new_settings]
    original_update_role_settings(self, settings)


import unicodedata
_marker = []
from BTrees.IIBTree import IITreeSet


def insertForwardIndexEntry(self, entry, documentId):
    """Take the entry provided and put it in the correct place
    in the forward index.

    This will also deal with creating the entire row if necessary.
    """
    try:
            indexRow = self._index.get(entry, _marker)
    except:
            entry = unicodedata.normalize('NFKD', entry.decode('utf-8')).encode('ascii', errors='ignore')
            indexRow = self._index.get(entry, _marker)

    # Make sure there's actually a row there already. If not, create
    # a set and stuff it in first.
    if indexRow is _marker:
        # We always use a set to avoid getting conflict errors on
        # multiple threads adding a new row at the same time
        self._index[entry] = IITreeSet((documentId, ))
        self._length.change(1)
    else:
        try:
            indexRow.insert(documentId)
        except AttributeError:
            # Inline migration: index row with one element was an int at
            # first (before Zope 2.13).
            indexRow = IITreeSet((indexRow, documentId))
            self._index[entry] = indexRow
