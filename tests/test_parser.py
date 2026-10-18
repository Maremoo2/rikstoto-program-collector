from collector.parsing import link_identity, parse_race, odds_from_text
from collector.pipeline import discover, race_url, summarize

URL = 'https://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6&p=6:0'


def sample_program():
    horses = [
       ('Skjetne Lara','Dag-Sveinung Dalen','7,72',1),
       ('Lesja Loke','Per Einar Sørmo','-',2),
       ('Norlilja','Monika Fremstad','75,82',3),
       ('Nyheims Filippa','Mari Pallin Mjøen','-',4),
       ('Maiken','Ragnhild Bjørnbeth','75,82',5),
       ('Kolli Amarok','Atle Solhus','6,95',6),
       ('Rofstad Lynet','Bjørn Garberg','1,26',7),
       ('Will Jahn','Inge Melby','75,82',8),
       ('Astriks','Jomar Blekkan','-',9),
       ('Millie Ø.K.','Ole Johnsen','38,80',10),
       ('Hansine S.','Thomas Mjøen','15,31',11),
       ('Kamiro','Linn Therese Sinnes','-',12),
       ('Heike Fra Skaråsen','Arve Sjoner','75,82',13),
       ('Kvikk Vinn','Jarle Morten Sørmo','75,82',14),
       ('Nyheims Mirakles','Veronika Bugge','37,91',15),
    ]
    odds = ['Odds - Vinner','Hest Vinner Min Max']
    for name, driver, price, no in horses:
        if price != '-':
            odds += [f'{no} {name}',f'{price} 1,00 6,46']
    main = ['Vinner','Varig Orkla','Løp 6','kl. 20:47','1720m','Voltestart','Travløp',
            'Velg alle', 'Nr.', 'Hest', 'Vinner', 'Tillegg','Innkjørt kr','Sko', 'Vogn']
    for i, (name, driver, price, no) in enumerate(horses):
        if i == 9: main.append('20 meter tillegg')
        main += [name,driver, f'{price} 71 636', f'Va {no if no<=9 else no-9} 31,8m 30,9am 44% 56% 50%',
                 '2026 : 8-4-0-1 , 30,9am 69 636',
                 '2025 : 1-0-0-0 , 35,3m 2 000','Tot : 9-4-0-1',
                 '5-års mørkbr hp','e Odd Herakles (NORGE) - Stina (NORGE)',
                 'Trener: Anne Dahlshaug (T), Eier: Stall Larris, Oppdretter: Anne Dahlshaug',
                 'KuskKusk BaneBane Dato, løp og sporDato - løp | spor NummerNr. DistanseDist. PlassPlass TidTid SkoSko VognVogn OddsOdds PremiePremie TrippelTrippel VideoVideo KommentarKommentar']
        for j in range(5):
            main += [f'Da Dal\tOA\t{20+j:02}.06.26 - {j+1}|03\t5\t2320\t3\t32,8\tVa\t48\t20\'\tAnnen hest 31,5',
                     f'Kommentar fra løp {j+1} for {name}']
    main += ['Andre spill til løpet:', 'Odds sist oppdatert I dag kl. 10:06', 'Strykninger',
             'Løp 6 V65-5, V5-2, DD-1 2 Lesja Loke',
             'Løp 10 V4-3 7 Global Finance (S)', 'Åpningstider for nettspill']
    return '\n'.join(odds + main)


def test_reference_race_has_15_and_14_active():
    race = parse_race(sample_program(), URL, captured_at='2026-10-18T08:06:00Z')
    assert race['race']['race_number'] == 6
    assert race['race']['meeting_id'] == 'OR_NR_2026-10-18'
    assert race['race']['track'] == 'Varig Orkla'
    assert race['qa']['entrant_count'] == 15
    assert race['qa']['active_count'] == 14
    assert race['qa']['scratched_count'] == 1
    assert race['qa']['past_start_rows'] == 75
    assert race['entrants'][1]['name'] == 'Lesja Loke'
    assert race['entrants'][1]['scratched']
    assert race['entrants'][1]['program_number'] == 2
    assert race['entrants'][3]['number_source'] == 'order_inferred_not_verified'
    assert race['win_odds'][0]['win_odds'] == 7.72
    assert race['entrants'][0]['past_starts'][0]['comment'].startswith('Kommentar')


def test_odds_parses_one_line_and_two_line():
    s='Odds - Vinner\n7 Rofstad Lynet\n1,26 1,00 1,29\n6 Kolli Amarok 6,95 1,00 6,08\nVinner\nVarig Orkla'
    r=odds_from_text(s)
    assert [x['horse_number'] for x in r] == [7,6]


def test_discovery_and_race_url():
    page='<a href="/Spill/OR_NR_2026-10-18/V?race=6&amp;p=6:0">Løp 6</a>'
    links=discover(page,'https://www.rikstoto.no/?date=2026-10-18','2026-10-18')
    assert len(links)==1 and 'race=6' in links[0]
    assert 'race=8' in race_url(URL,8) and 'p=8%3A0' in race_url(URL,8)


def test_summary_fails_closed_without_races():
    p={'races':[],'captures':[], 'discovery':{'status':'candidate_only'}}
    assert summarize(p, 1)['status']=='REVIEW_REQUIRED'
    assert 'NO_RACES_PARSED' in summarize(p, 1)['warnings']

def test_historical_table_preserves_tab_columns_and_respects_missing_ones():
    race = parse_race(sample_program(), URL, captured_at='2026-10-18T08:06:00Z')
    start = race['entrants'][0]['past_starts'][0]
    assert start['starter_number'] == 5
    assert start['distance_m'] == 2320
    assert start['placing'] == '3'
    assert start['kilometre_time'] == '32,8'
    # This synthetic fixture lacks a separate wagon cell; it must not be
    # shifted into an incorrect odds/prize column.
    assert start['odds_display'] is None
    assert start['prize_display'] is None


def test_historical_table_with_complete_columns():
    raw = sample_program().replace("\t32,8\tVa\t48\t20'", "\t32,8\t\tVa\t48\t20'")
    race = parse_race(raw, URL, captured_at='2026-10-18T08:06:00Z')
    start = race['entrants'][0]['past_starts'][0]
    assert start['shoes'] is None
    assert start['wagon'] == 'Va'
    assert start['odds_display'] == '48'
    assert start['prize_display'] == "20'"
