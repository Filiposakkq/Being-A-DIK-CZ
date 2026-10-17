"""Menus of a game script: the choices, the question or the lines before, what follows each choice; and the app call that joins them with the translation."""
import unittest

from helpers import TempCase

from prehled import menus

SCRIPT = [
    'label start:',                                  # 1
    '    scene room',                                # 2
    '    mc "I need coffee."',                       # 3
    '    js "Same."',                                # 4
    '    menu:',                                     # 5
    '        "Invite her" if met_her:',              # 6
    '            mc "Want a coffee?"',               # 7
    '            js "Sure."',                        # 8
    '            jump cafe',                         # 9
    '        "Leave":',                              # 10
    '            "You walk away."',                  # 11
    '            menu:',                             # 12
    '                "Look back":',                  # 13
    '                    mc "Bye."',                 # 14
    '                "Do not":',                     # 15
    '                    pass',                      # 16
    '    mc "Later."',                               # 17
    '    menu:',                                     # 18
    '        mc "What now?"',                        # 19
    '        "Sleep":',                              # 20
    '            return',                            # 21
]


class FindMenuTests(unittest.TestCase):
    def test_a_menu_without_a_question_gives_the_lines_said_before_it(self):
        m = menus.find_menu(SCRIPT, 10)
        self.assertEqual((m["menu_line"], m["question"], m["before"]), (5, [], [3, 4]))
        self.assertEqual([(o["n"], o["text"], o["cond"], o["after"]) for o in m["options"]],
                         [(6, "Invite her", "met_her", [7, 8]), (10, "Leave", "", [11])])         # the inner menu is not part of "Leave"
        self.assertEqual(m["current"], 1)

    def test_ren_py_may_record_the_line_of_the_menu_for_every_choice(self):
        m = menus.find_menu(SCRIPT, 5, "Leave")                                    # the ref of every choice of this menu is line 5
        self.assertEqual((m["menu_line"], [o["text"] for o in m["options"]], m["current"]), (5, ["Invite her", "Leave"], 1))
        self.assertEqual(menus.find_menu(SCRIPT, 5, "  Invite   her ")["current"], 0)       # white space does not matter
        self.assertEqual(menus.find_menu(SCRIPT, 5)["current"], -1)                         # without the text no choice is marked
        self.assertEqual(menus.find_menu(SCRIPT, 12, "Do not")["current"], 1)

    def test_a_menu_inside_a_choice_is_found_on_its_own(self):
        m = menus.find_menu(SCRIPT, 15)
        self.assertEqual((m["menu_line"], [o["text"] for o in m["options"]], m["current"]), (12, ["Look back", "Do not"], 1))

    def test_a_question_inside_the_menu_replaces_the_lines_before_it(self):
        m = menus.find_menu(SCRIPT, 20)
        self.assertEqual((m["menu_line"], m["question"], m["before"]), (18, [19], []))

    def test_a_line_that_is_no_choice_gives_nothing(self):
        self.assertIsNone(menus.find_menu(SCRIPT, 3))
        self.assertIsNone(menus.find_menu(SCRIPT, 99))
        self.assertIsNone(menus.find_menu(['label a:', '    "Text":', '        pass'], 2))        # a string with a colon, but no menu above

    def test_what_is_a_line_of_dialogue(self):
        for line in ('    "Hi."', '    mc "Hi."', '    mc happy "Hi." with vpunch', "    mc 'Hi.'"):
            self.assertTrue(menus.is_say(line), line)
        for line in ('    show anna "x"', '    jump cafe', '    $ x = "a"', '    # mc "Hi."', '    if x == "a":', '    play music "a.ogg"'):
            self.assertFalse(menus.is_say(line), line)


NESTED = [
    'label a:',                                      # 1
    '    mc "Before the if."',                       # 2
    '    if x:',                                     # 3
    '        mc "In the if branch."',                # 4
    '    else:',                                     # 5
    '        menu:',                                 # 6
    '            "Warm it up":',                     # 7
    '                na "You warm it."',             # 8
    '            "Leave it":',                       # 9
    '                $ y = 1',                       # 10
    '    mc "After."',                               # 11
    '    menu:',                                     # 12
    '        "A":',                                  # 13
    '            mc "Said A."',                      # 14
    '            if y:',                             # 15
    '                mc "Deep in A."',               # 16
    '        "B":',                                  # 17
    '            pass',                              # 18
]


class MenuAroundTests(unittest.TestCase):
    def test_a_menu_that_opens_an_if_block_looks_back_past_the_if_but_not_into_a_sibling_branch(self):
        self.assertEqual(menus.find_menu(NESTED, 6)["before"], [2])          # not "In the if branch." (another path), nor the lines of an earlier menu
        self.assertEqual(menus.find_menu(NESTED, 12)["before"], [2, 11])     # the bodies of the first menu are skipped; the if / else is walked over

    def test_a_choice_without_dialogue_keeps_the_first_lines_of_its_body(self):
        m = menus.find_menu(NESTED, 12)
        self.assertEqual(m["options"][1]["body"], ["            pass"])
        self.assertEqual(menus.find_menu(NESTED, 6)["options"][1]["body"], ["                $ y = 1"])
        lines = ['menu:', '    "Yes":', '        $ x += 1', '        show a 3', '        menu Q2:', '            "Deep":', '                pass', '        $ ignored = 1']
        self.assertEqual(menus.find_menu(lines, 2)["options"][0]["body"], ['        $ x += 1', '        show a 3', '        menu Q2:', '            "Deep":'])

    def test_the_lines_of_a_choice_belong_to_its_menu(self):
        self.assertEqual(menus.menu_around(NESTED, 14)["menu_line"], 12)     # first line of the body of A
        self.assertEqual(menus.menu_around(NESTED, 16)["menu_line"], 12)     # inside an `if` in the body: beyond the lines the menu shows? it is the 2nd say line
        self.assertEqual(menus.menu_around(NESTED, 8)["menu_line"], 6)

    def test_the_line_said_before_a_menu_belongs_to_it_but_a_far_one_does_not(self):
        self.assertEqual(menus.menu_around(NESTED, 11)["menu_line"], 12)
        self.assertEqual(menus.menu_around(NESTED, 2)["menu_line"], 6)       # `if` / `else` between: the menu is still the next thing the story reaches
        self.assertIsNone(menus.menu_around(['label a:', '    mc "x."', '    mc "y."', '    mc "z."', '    menu:', '        "A":', '            pass'], 2))   # only the last two lines


class MenuInTheAppTests(TempCase):
    def test_the_choice_is_joined_with_its_menu_the_question_and_the_translations(self):
        game = self.tmp / "game"
        tl = game / "tl" / "czech"
        tl.mkdir(parents=True)
        (game / "script.rpy").write_text("\n".join(SCRIPT) + "\n", encoding="utf-8")
        (tl / "script.rpy").write_text(
            '# game/script.rpy:3\ntranslate czech a_1:\n\n    # mc "I need coffee."\n    mc "Potřebuju kafe."\n\n'
            '# game/script.rpy:4\ntranslate czech a_2:\n\n    # js "Same."\n    js "Taky."\n\n'
            '# game/script.rpy:7\ntranslate czech a_3:\n\n    # mc "Want a coffee?"\n    mc "Dáš si kafe?"\n\n'
            'translate czech strings:\n\n'
            '    # game/script.rpy:6\n    old "Invite her"\n    new "Pozvat ji"\n\n'
            '    # game/script.rpy:10\n    old "Leave"\n    new "Odejít"\n\n', encoding="utf-8")
        app = self.new_app(open_root=False)
        app.open_project(tl)
        leave = next(e for e in app.project.entries("script.rpy") if e.unit == "string" and e.source == "Leave")
        r = app.entry_menu("script.rpy", leave.line)
        self.assertTrue(r["available"])
        self.assertEqual([x["entry"]["target"] for x in r["before"]], ["Potřebuju kafe.", "Taky."])
        self.assertEqual([(o["text"], o["entry"]["target"], o["current"]) for o in r["options"]], [("Invite her", "Pozvat ji", False), ("Leave", "Odejít", True)])
        self.assertEqual(r["options"][0]["after"][0]["entry"]["target"], "Dáš si kafe?")       # what follows the choice
        self.assertIsNone(r["options"][0]["after"][1]["entry"])                                    # not in the translation: the script line is shown
        self.assertEqual(r["options"][0]["after"][1]["script"], 'js "Sure."')
        dialogue = next(e for e in app.project.entries("script.rpy") if e.unit == "dialogue" and e.source == "Same.")      # said just before the menu
        r = app.entry_menu("script.rpy", dialogue.line)
        self.assertTrue(r["available"])
        self.assertEqual([x["here"] for x in r["before"]], [False, True])                                      # the open line is marked
        self.assertFalse(any(x["here"] for o in r["options"] for x in o["after"]))


    def test_choices_recorded_at_the_menu_line_are_told_apart_by_their_text(self):
        game = self.tmp / "game"
        tl = game / "tl" / "czech"
        tl.mkdir(parents=True)
        (game / "script.rpy").write_text("\n".join(SCRIPT) + "\n", encoding="utf-8")
        (tl / "script.rpy").write_text(
            'translate czech strings:\n\n    # game/script.rpy:5\n    old "Invite her"\n    new "Pozvat ji"\n\n'
            '    # game/script.rpy:5\n    old "Leave"\n    new "Odejít"\n\n', encoding="utf-8")
        app = self.new_app(open_root=False)
        app.open_project(tl)
        leave = next(e for e in app.project.entries("script.rpy") if e.source == "Leave")
        r = app.entry_menu("script.rpy", leave.line)
        self.assertEqual([(o["text"], o["current"]) for o in r["options"]], [("Invite her", False), ("Leave", True)])

    def test_a_choice_text_used_in_an_earlier_menu_is_marked_with_the_place_where_it_is_listed(self):
        game = self.tmp / "game"
        tl = game / "tl" / "czech"
        tl.mkdir(parents=True)
        (game / "script.rpy").write_text("\n".join(SCRIPT) + "\n", encoding="utf-8")
        (tl / "script.rpy").write_text(
            'translate czech strings:\n\n    # game/script.rpy:100\n    old "Leave"\n    new "Odejít"\n\n'
            '    # game/script.rpy:5\n    old "Invite her"\n    new "Pozvat ji"\n\n', encoding="utf-8")
        app = self.new_app(open_root=False)
        app.open_project(tl)
        invite = next(e for e in app.project.entries("script.rpy") if e.source == "Invite her")
        r = app.entry_menu("script.rpy", invite.line)
        self.assertEqual([(o["text"], o["where"]) for o in r["options"]], [("Invite her", ""), ("Leave", "game/script.rpy:100")])


if __name__ == "__main__":
    unittest.main()
