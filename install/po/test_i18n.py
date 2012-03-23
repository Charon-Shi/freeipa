#!/usr/bin/python
# Authors:
#   John Dennis <jdennis@redhat.com>
#
# Copyright (C) 2010  Red Hat
# see file 'COPYING' for use and warranty information
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import optparse
import sys
import gettext
import locale
import re
import os
import traceback
import polib

'''
We test our translations by taking the original untranslated string
(e.g. msgid) and prepend a prefix character and then append a suffix
character. The test consists of asserting that the first character in the
translated string is the prefix, the last character in the translated string
is the suffix and the everything between the first and last character exactly
matches the original msgid.

We use unicode characters not in the ascii character set for the prefix and
suffix to enhance the test. To make reading the translated string easier the
prefix is the unicode right pointing arrow and the suffix left pointing arrow,
thus the translated string looks like the original string enclosed in
arrows. In ASCII art the string "foo" would render as:
-->foo<--
'''

#-------------------------------------------------------------------------------

verbose = False
print_traceback = False
pedantic = False
show_strings = True

# Unicode right pointing arrow
prefix = u'\u2192'               # utf-8 == '\xe2\x86\x92'
# Unicode left pointing arrow
suffix = u'\u2190'               # utf-8 == '\xe2\x86\x90'

page_width = 80
section_seperator = '=' * page_width
entry_seperator = '-' * page_width

#-------------------------------------------------------------------------------
# For efficiency compile these regexps just once
_substitution_regexps = [re.compile(r'%[srduoxf]\b'),        # e.g. %s
                         re.compile(r'%\(\w+\)[srduoxf]\b'), # e.g. %(foo)s
                         re.compile(r'\$\w+'),               # e.g. $foo
                         re.compile(r'\${\w+}'),             # e.g. ${foo}
                         re.compile(r'\$\(\w+\)')            # e.g. $(foo)
                         ]
# Python style substitution, e.g. %(foo)s
# where foo is the key and s is the format char
# group 1: whitespace between % and (
# group 2: whitespace between ( and key
# group 3: whitespace between key and )
# group 4: whitespace between ) and format char
# group 5: format char
_python_substitution_regexp = re.compile(r'%(\s*)\((\s*)\w+(\s*)\)(\s*)([srduoxf]\b)?')

# Shell style substitution, e.g. $foo $(foo) ${foo}
# where foo is the variable
_shell_substitution_regexp = re.compile(r'\$(\s*)([({]?)(\s*)\w+(\s*)([)}]?)')
# group 1: whitespace between $ and delimiter
# group 2: begining delimiter
# group 3: whitespace between beginning delmiter and variable
# group 4: whitespace between variable and ending delimiter
# group 5: ending delimiter

# We do not permit anonymous substitutions in translation strings
# (e.g. '%s occurred' % error) because they do not provide the
# necessary context to translators, they would only see
# '%s occurred'. Instead a keyword substitution should be used
# (e.g. '%(error)s occurred' % {'error': error_message})

# Python anonymous format substitutions, e.g. %s, %d, %f, etc.
python_anonymous_substitutions_regexp = re.compile(r'%[srduoxf]\b') # e.g. %s

def validate_substitutions_match(s1, s2, s1_name='string1', s2_name='string2'):
    '''
    Validate both s1 and s2 have the same number of substitution strings.
    A substitution string would be something that looked like this:

    * %(foo)s
    * $foo
    * ${foo}
    * $(foo)

    The substitutions may appear in any order in s1 and s2, however their
    format must match exactly and the exact same number of each must exist
    in both s1 and s2.

    A list of error diagnostics is returned explaining how s1 and s2 failed
    the validation check. If the returned error list is empty then the
    validation succeeded.

    :param s1:      First string to validate
    :param s2:      First string to validate
    :param s1_name: In diagnostic messages the name for s1
    :param s2_name: In diagnostic messages the name for s2
    :return:        List of diagnostic error messages, if empty then success
    '''
    errors = []

    def get_subs(s):
        '''
        Return a dict whoses keys are each unique substitution and whose
        value is the count of how many times that substitution appeared.
        '''
        subs = {}
        for regexp in _substitution_regexps:
            for match in regexp.finditer(s):
                matched = match.group(0)
                subs[matched] = subs.get(matched, 0) + 1
        return subs

    # Get the substitutions and their occurance counts
    subs1 = get_subs(s1)
    subs2 = get_subs(s2)

    # Form a set for each strings substitutions and
    # do set subtraction and interesection
    set1 = set(subs1.keys())
    set2 = set(subs2.keys())

    missing1 = set2 - set1
    missing2 = set1 - set2
    common = set1 & set2

    # Test for substitutions which are absent in either string
    if missing1:
        errors.append("The following substitutions are absent in %s: %s" %
                      (s1_name, ' '.join(missing1)))

    if missing2:
        errors.append("The following substitutions are absent in %s: %s" %
                      (s2_name, ' '.join(missing2)))

    if pedantic:
        # For the substitutions which are shared assure they occur an equal number of times
        for sub in common:
            if subs1[sub] != subs2[sub]:
                errors.append("unequal occurances of '%s', %s has %d occurances, %s has %d occurances" %
                              (sub, s1_name, subs1[sub], s2_name, subs2[sub]))

    if errors:
        if show_strings:
            errors.append('>>> %s <<<' % s1_name)
            errors.append(s1.rstrip())

            errors.append('>>> %s <<<' % s2_name)
            errors.append(s2.rstrip())
    return errors


def validate_substitution_syntax(s, s_name='string'):
    '''
    If s has one or more substitution variables then validate they
    are syntactically correct.
    A substitution string would be something that looked like this:

    * %(foo)s
    * $foo
    * ${foo}
    * $(foo)

    A list of error diagnostics is returned explaining how s1 and s2 failed
    the validation check. If the returned error list is empty then the
    validation succeeded.

    :param s:      String to validate
    :param s_name: In diagnostic messages the name for s
    :return:       List of diagnostic error messages, if empty then success
    '''
    errors = []

    # Look for Python style substitutions, e.g. %(foo)s
    for match in _python_substitution_regexp.finditer(s):
        if match.group(1):
            errors.append("%s has whitespace between %% and key in '%s'" %
                          (s_name, match.group(0)))
        if match.group(2) or match.group(3):
            errors.append("%s has whitespace next to key in '%s'" %
                          (s_name, match.group(0)))
        if match.group(4):
            errors.append("%s has whitespace between key and format character in '%s'" %
                          (s_name, match.group(0)))
        if not match.group(5):
            errors.append("%s has no format character in '%s'" %
                          (s_name, match.group(0)))

    # Look for shell style substitutions, e.g. $foo $(foo) ${foo}
    for match in _shell_substitution_regexp.finditer(s):
        if match.group(1):
            errors.append("%s has whitespace between $ and variable in '%s'" %
                          (s_name, match.group(0)))
        if match.group(3) or (match.group(4) and match.group(5)):
            errors.append("%s has whitespace next to variable in '%s'" %
                          (s_name, match.group(0)))

        beg_delimiter = match.group(2)
        end_delimiter = match.group(5)
        matched_delimiters = {'': '', '(': ')', '{': '}'}
        if beg_delimiter is not None or end_delimiter is not None:
            if matched_delimiters[beg_delimiter] != end_delimiter:
                errors.append("%s variable delimiters do not match in '%s', begin delimiter='%s' end delimiter='%s'" %
                              (s_name, match.group(0), beg_delimiter, end_delimiter))

    if errors:
        if show_strings:
            errors.append('>>> %s <<<' % s_name)
            errors.append(s.rstrip())

    return errors


def validate_anonymous_substitutions(s, s_name='string'):
    '''
    We do not permit multiple anonymous substitutions in translation
    strings (e.g. '%s') because they do not allow translators to reorder the
    wording. Instead keyword substitutions should be used when there are
    more than one.
    '''
    errors = []


    matches = list(python_anonymous_substitutions_regexp.finditer(s))

    if len(matches) > 1:
        for match in python_anonymous_substitutions_regexp.finditer(s):
            errors.append("%s has anonymous substitution '%s', use keyword substitution instead" %
                          (s_name, match.group(0)))

    if errors:
        if show_strings:
            errors.append('>>> %s <<<' % s_name)
            errors.append(s.rstrip())

    return errors

def validate_file(file_path, validation_mode):
    '''
    Given a pot or po file scan all it's entries looking for problems
    with variable substitutions. See the following functions for
    details on how the validation is performed.

    * validate_substitutions_match()
    * validate_substitution_syntax()
    * validate_anonymous_substitutions()

    Returns the number of entries with errors.
    '''

    error_lines = []
    n_entries_with_errors = 0

    if not os.path.isfile(file_path):
        print >>sys.stderr, 'file does not exist "%s"' % (file_path)
        return 1
    try:
        po = polib.pofile(file_path)
    except Exception, e:
        print >>sys.stderr, 'Unable to parse file "%s": %s' % (file_path, e)
        return 1

    for entry in po:
        entry_errors = []
        msgid = entry.msgid
        msgstr = entry.msgstr
        have_msgid = msgid.strip() != ''
        have_msgstr = msgstr.strip() != ''
        if validation_mode == 'pot':
            if have_msgid:
                errors = validate_anonymous_substitutions(msgid, 'msgid')
                entry_errors.extend(errors)
        if validation_mode == 'po':
            if have_msgid and have_msgstr:
                errors = validate_substitutions_match(msgid, msgstr, 'msgid', 'msgstr')
                entry_errors.extend(errors)
        if pedantic:
            if have_msgid:
                errors = validate_substitution_syntax(msgid, 'msgid')
                entry_errors.extend(errors)
            if have_msgstr:
                errors = validate_substitution_syntax(msgstr, 'msgstr')
                entry_errors.extend(errors)
        if entry_errors:
            error_lines.append(entry_seperator)
            error_lines.append('locations: %s' % (', '.join(["%s:%d" % (x[0], int(x[1])) for x in entry.occurrences])))
            error_lines.extend(entry_errors)
            n_entries_with_errors += 1
    if n_entries_with_errors:
        error_lines.insert(0, section_seperator)
        error_lines.insert(1, "%d validation errors in %s" % (n_entries_with_errors, file_path))
        print '\n'.join(error_lines)

    return n_entries_with_errors


#----------------------------------------------------------------------
def create_po(pot_file, po_file, mo_file):

    if not os.path.isfile(pot_file):
        print >>sys.stderr, 'file does not exist "%s"' % (pot_file)
        return 1
    try:
        po = polib.pofile(pot_file)
    except Exception, e:
        print >>sys.stderr, 'Unable to parse file "%s": %s' % (pot_file, e)
        return 1

    # Update the metadata in the po file header
    # It's case insensitive so search the keys in a case insensitive manner
    #
    # We need to update the Plural-Forms otherwise gettext.py will raise the
    # following error:
    #
    # raise ValueError, 'plural forms expression could be dangerous'
    #
    # It is demanding the rhs of plural= only contains the identifer 'n'

    for k,v in po.metadata.items():
        if k.lower() == 'plural-forms':
            po.metadata[k] = 'nplurals=2; plural=(n != 1)'
            break


    # Iterate over all msgid's and form a the msgstr by prepending
    # the prefix and appending the suffix
    for entry in po:
        if entry.msgid_plural:
            entry.msgstr_plural = {0: prefix + entry.msgid + suffix,
                                   1: prefix + entry.msgid_plural + suffix}
        else:
            entry.msgstr = prefix + entry.msgid + suffix

    # Write out the po and mo files
    po.save(po_file)
    print "Wrote: %s" % (po_file)

    po.save_as_mofile(mo_file)
    print "Wrote: %s" % (mo_file)

    return 0

#----------------------------------------------------------------------

def validate_unicode_edit(msgid, msgstr):
    # Verify the first character is the test prefix
    if msgstr[0] != prefix:
        raise ValueError('First char in translated string "%s" not equal to prefix "%s"' %
                         (msgstr.encode('utf-8'), prefix.encode('utf-8')))

    # Verify the last character is the test suffix
    if msgstr[-1] != suffix:
        raise ValueError('Last char in translated string "%s" not equal to suffix "%s"' %
                         (msgstr.encode('utf-8'), suffix.encode('utf-8')))

    # Verify everything between the first and last character is the
    # original untranslated string
    if msgstr[1:-1] != msgid:
        raise ValueError('Translated string "%s" minus the first & last character is not equal to msgid "%s"' %
                         (msgstr.encode('utf-8'), msgid))

    if verbose:
        msg = 'Success: message string "%s" maps to translated string "%s"' % (msgid, msgstr)
        print msg.encode('utf-8')


def test_translations(po_file, lang, domain, locale_dir):
    try:

        # The test installs the test message catalog under the xh_ZA
        # (e.g. Zambia Xhosa) language by default. It would be nice to
        # use a dummy language not associated with any real language,
        # but the setlocale function demands the locale be a valid
        # known locale, Zambia Xhosa is a reasonable choice :)

        os.environ['LANG'] = lang

        # Create a gettext translation object specifying our domain as
        # 'ipa' and the locale_dir as 'test_locale' (i.e. where to
        # look for the message catalog). Then use that translation
        # object to obtain the translation functions.

        t = gettext.translation(domain, locale_dir)

        # Iterate over the msgid's
        if not os.path.isfile(po_file):
            print >>sys.stderr, 'file does not exist "%s"' % (po_file)
            return 1
        try:
            po = polib.pofile(po_file)
        except Exception, e:
            print >>sys.stderr, 'Unable to parse file "%s": %s' % (po_file, e)
            return 1

        n_entries = 0
        n_translations = 0
        n_valid = 0
        n_fail = 0
        for entry in po:
            if entry.msgid_plural:
                msgid = entry.msgid
                msgid_plural = entry.msgid_plural
                msgstr = t.ungettext(msgid, msgid_plural, 1)
                msgstr_plural = t.ungettext(msgid, msgid_plural, 2)

                try:
                    n_translations += 1
                    validate_unicode_edit(msgid, msgstr)
                    n_valid += 1
                except Exception, e:
                    n_fail += 1
                    if print_traceback:
                        traceback.print_exc()
                    print >> sys.stderr, "ERROR: %s" % e

                try:
                    n_translations += 1
                    validate_unicode_edit(msgid_plural, msgstr_plural)
                    n_valid += 1
                except Exception, e:
                    n_fail += 1
                    if print_traceback:
                        traceback.print_exc()
                    print >> sys.stderr, "ERROR: %s" % e


            else:
                msgid = entry.msgid
                msgstr = t.ugettext(msgid)

                try:
                    n_translations += 1
                    validate_unicode_edit(msgid, msgstr)
                    n_valid += 1
                except Exception, e:
                    n_fail += 1
                    if print_traceback:
                        traceback.print_exc()
                    print >> sys.stderr, "ERROR: %s" % e

            n_entries += 1

    except Exception, e:
        if print_traceback:
            traceback.print_exc()
        print >> sys.stderr, "ERROR: %s" % e
        return 1

    if not n_entries:
        print >> sys.stderr, "ERROR: no translations found in %s" % (po_filename)
        return 1

    if n_fail:
        print >> sys.stderr, "ERROR: %d failures out of %d translations" % (n_fail, n_entries)
        return 1

    print "%d translations in %d messages successfully tested" % (n_translations, n_entries)
    return 0

#----------------------------------------------------------------------

usage ='''

%prog --test-gettext
%prog --create-test
%prog --validate-pot [pot_file1, ...]
%prog --validate-po po_file1 [po_file2, ...]
'''

def main():
    global verbose, print_traceback, pedantic, show_strings

    parser = optparse.OptionParser(usage=usage)

    mode_group = optparse.OptionGroup(parser, 'Operational Mode',
                                      'You must select one these modes to run in')

    mode_group.add_option('-g', '--test-gettext', action='store_const', const='test_gettext', dest='mode',
                          help='create the test translation file(s) and exercise them')
    mode_group.add_option('-c', '--create-test', action='store_const', const='create_test', dest='mode',
                          help='create the test translation file(s)')
    mode_group.add_option('-P', '--validate-pot', action='store_const', const='validate_pot', dest='mode',
                          help='validate pot file(s)')
    mode_group.add_option('-p', '--validate-po', action='store_const', const='validate_po', dest='mode',
                          help='validate po file(s)')

    parser.add_option_group(mode_group)
    parser.set_defaults(mode='')

    parser.add_option('-s', '--show-strings', action='store_true', dest='show_strings', default=False,
                      help='show the offending string when an error is detected')
    parser.add_option('--pedantic', action='store_true', dest='pedantic', default=False,
                      help='be aggressive when validating')
    parser.add_option('-v', '--verbose', action='store_true', dest='verbose', default=False,
                      help='be informative')
    parser.add_option('--traceback', action='store_true', dest='print_traceback', default=False,
                      help='print the traceback when an exception occurs')

    param_group = optparse.OptionGroup(parser, 'Run Time Parameters',
                                       'These may be used to modify the run time defaults')

    param_group.add_option('--test-lang', action='store', dest='test_lang', default='test',
                           help="test po file uses this as it's basename (default=test)")
    param_group.add_option('--lang', action='store', dest='lang', default='xh_ZA',
                           help='lang used for locale, MUST be a valid lang (default=xh_ZA)')
    param_group.add_option('--domain', action='store', dest='domain', default='ipa',
                           help='translation domain used during test (default=ipa)')
    param_group.add_option('--locale-dir', action='store', dest='locale_dir', default='test_locale',
                           help='locale directory used during test (default=test_locale)')
    param_group.add_option('--pot-file', action='store', dest='pot_file', default='ipa.pot',
                           help='default pot file, used when validating pot file or generating test po and mo files (default=ipa.pot)')

    parser.add_option_group(param_group)

    options, args = parser.parse_args()

    verbose = options.verbose
    print_traceback = options.print_traceback
    pedantic = options.pedantic
    show_strings = options.show_strings

    if not options.mode:
        print >> sys.stderr, 'ERROR: no mode specified'
        return 1

    if options.mode == 'validate_pot' or options.mode == 'validate_po':
        if options.mode == 'validate_pot':
            files = args
            if not files:
                files = [options.pot_file]
            validation_mode = 'pot'
        elif options.mode == 'validate_po':
            files = args
            if not files:
                print >> sys.stderr, 'ERROR: no po files specified'
                return 1
            validation_mode = 'po'
        else:
            print >> sys.stderr, 'ERROR: unknown validation mode "%s"' % (options.mode)
            return 1

        total_errors = 0
        for f in files:
            n_errors = validate_file(f, validation_mode)
            total_errors += n_errors
        if total_errors:
            print section_seperator
            print "%d errors in %d files" % (total_errors, len(files))
            return 1
        else:
            return 0

    elif options.mode == 'create_test' or 'test_gettext':
        po_file = '%s.po' % options.test_lang
        pot_file = options.pot_file

        msg_dir = os.path.join(options.locale_dir, options.lang, 'LC_MESSAGES')
        if not os.path.exists(msg_dir):
            os.makedirs(msg_dir)

        mo_basename = '%s.mo' % options.domain
        mo_file = os.path.join(msg_dir, mo_basename)

        result = create_po(pot_file, po_file, mo_file)
        if result:
            return result

        if options.mode == 'create_test':
            return result

        # The test installs the test message catalog under the xh_ZA
        # (e.g. Zambia Xhosa) language by default. It would be nice to
        # use a dummy language not associated with any real language,
        # but the setlocale function demands the locale be a valid
        # known locale, Zambia Xhosa is a reasonable choice :)

        lang = options.lang

        # Create a gettext translation object specifying our domain as
        # 'ipa' and the locale_dir as 'test_locale' (i.e. where to
        # look for the message catalog). Then use that translation
        # object to obtain the translation functions.

        domain = options.domain
        locale_dir = options.locale_dir

        return test_translations(po_file, lang, domain, locale_dir)

    else:
        print >> sys.stderr, 'ERROR: unknown mode "%s"' % (options.mode)
        return 1

if __name__ == "__main__":
    sys.exit(main())
