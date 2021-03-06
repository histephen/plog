__all__ = ('markup', )

from cMarkdown import markdown
from HTMLParser import HTMLParser
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.lexer import Lexer
from pygments.lexers.templates import HtmlDjangoLexer
from pygments.lexers.agile import PythonLexer
from pygments.token import Text
import re

class PlainHtmlFormatter(HtmlFormatter):

    def wrap(self, source, outfile):
        return self.__wrap(source)

    def __wrap(self, source):
        for i, t in source:
            yield i, t


class PreCodeFinder(HTMLParser):

    def reset(self):
        HTMLParser.reset(self)
        self.stack = []
        self.data = []
        self.out = []

    def close(self):
        HTMLParser.close(self)
        return ''.join(self.out)

    def handle_startendtag(self, tag, attrs):
        if attrs:
            self.out.append("<%s %s/>" % (tag, ' '.join('%s="%s"' % (k, v) for k, v in attrs)))
        else:
            self.out.append("<%s/>" % tag)

    def handle_starttag(self, tag, attrs):
        if tag == 'pre' and self.stack == []:
            self.stack.append(tag)
        elif tag == 'code' and self.stack == ['pre']:
            self.stack.append(tag)

        if attrs:
            self.out.append("<%s %s/>" % (tag, ' '.join('%s="%s"' % (k, v) for k, v in attrs)))
        else:
            self.out.append("<%s>" % tag)

    def handle_data(self, data):
        if self.stack == ['pre', 'code']:
            self.data.append(data)
        else:
            self.out.append(data)

    def handle_endtag(self, tag):
        if self.data:
            if ':::' in self.data[0]:
                # parts of self.data will have \n in them
                data = ''.join(self.data)
                lines = data.split('\n')
                firstline, lines = lines[0], lines[1:]
                lang = firstline.strip()[3:].strip()
                lexer = get_lexer_by_name(lang)
                self.out.append(highlight('\n'.join(lines), lexer, PlainHtmlFormatter(nowrap=True)))
            else:
                self.out.append('\n'.join(self.data))
            self.data = []
        if self.stack and tag == self.stack[-1]:
            self.stack.pop(-1)
        self.out.append('</%s>' % tag)

    def handle_entityref(self, name):
        if self.stack == ['pre', 'code']:
            if name == 'quot':
                self.data.append('"')
            elif name == 'gt':
                self.data.append('>')
            elif name == 'lt':
                self.data.append('<')
            else:
                self.data.append('&%s;' % name)
        else:
            self.out.append('&%s;' % name)


class KeystoneLexer(Lexer):
    name = 'keystone'
    aliases = ['keystone']
    filenames = ['*.ks']

    def __init__(self, **options):
        self.options = options.copy()
        super(KeystoneLexer, self).__init__(**options)

    def get_tokens_unprocessed(self, text):
        offset = 0
        if re.search(r'^----\s*$', text, re.MULTILINE):
            py, _, text = text.partition('----')

            lexer = PythonLexer(**self.options)
            for i, token, value in lexer.get_tokens_unprocessed(py):
                yield i, token, value

            offset = i + 1
            yield offset, Text, u'----'
            offset += 1

        lexer = HtmlDjangoLexer(**self.options)
        for i, token, value in lexer.get_tokens_unprocessed(text):
            yield offset + i, token, value


def markup(text):
    html = markdown(text,  smartypants=True)
    pcf = PreCodeFinder()
    pcf.feed(html)
    return pcf.close()

