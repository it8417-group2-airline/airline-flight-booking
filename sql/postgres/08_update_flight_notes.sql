-- =====================================================================
-- File   : 08_update_flight_notes.sql   (Abrar - Member 1)
-- Purpose: Give every flight its own disruption note.
--   Before: 54 notes but only 28 different texts (one sentence repeated
--   14 times), so the semantic search returned identical, tied results.
--   After : 54 unique notes, each matching the flight's real route,
--   status and delay. Flights 9 and 31 keep their planted NULL notes.
-- Run ONCE in the Supabase SQL Editor, then re-run the embedding script:
--   python vector/embed_flight_notes.py --rebuild
-- (03_mainline_carrier_seed.sql already contains the same notes, so a
--  fresh rebuild from 01-04 does not need this file.)
-- =====================================================================

UPDATE mainline_carrier.flight AS f
SET notes = n.note
FROM (VALUES
  (1, 'Departed four minutes ahead of schedule on a light load; quick turnaround at Dubai Terminal 1 and no irregularities reported.'),
  (2, 'Early pushback from Dubai after boarding finished ahead of time; calm evening sector and cabin report praised the dessert service.'),
  (3, 'Departed exactly on time with a busy Economy cabin; many passengers connecting onward from Doha to Europe and every connection was protected.'),
  (4, 'Short Doha shuttle completed early; two wheelchair-assistance passengers were handled smoothly by ground staff on arrival.'),
  (5, 'On-time evening service to Riyadh; travel document checks at the gate went quickly and there were no denied boardings.'),
  (6, 'Bird strike reported on climb-out from Riyadh; aircraft returned to stand for an engineering inspection, no damage found, and departed again 2 hours 40 minutes late.'),
  (7, 'Hydrant fuelling pressure fault at the Bahrain stand; a fuel bowser was called in as backup and departure slipped by 40 minutes.'),
  (8, 'Dense morning fog at Jeddah triggered low-visibility procedures and an ATC ground stop; 95-minute hold and several passengers missed onward connections at the Bahrain hub.'),
  (10, 'Inbound aircraft arrived late from its previous rotation; knock-on 50-minute delay out of Kuwait despite a shortened turnaround.'),
  (11, 'Night departure to Muscat left 5 minutes late after a short taxi queue; positive passenger feedback on the new seat-back screens.'),
  (12, 'Small 7-minute delay waiting for a late-checked transfer bag at Muscat; tailwinds meant the aircraft still landed in Bahrain on schedule.'),
  (13, 'Arrival flow restrictions at London Heathrow because of strong westerly winds; the aircraft waited 45 minutes in Bahrain for its departure slot.'),
  (14, 'Cancelled after thick overnight fog closed the Heathrow runways; all passengers rebooked on the next day''s departure with hotel rooms provided.'),
  (15, 'Thunderstorm with lightning close to Bahrain airport suspended all ramp work for 50 minutes; baggage loading paused and the Paris departure was delayed.'),
  (16, 'Departed Paris on schedule with a near-full Business cabin; arrived in Bahrain on time and all Gulf connections were made.'),
  (17, 'Unruly passenger refused crew instructions after take-off and police met the aircraft in Istanbul; the departure itself was only 5 minutes late.'),
  (18, 'Departure 8 minutes behind schedule because of a congested pushback area at Istanbul; one family was upgraded to Business after an overbooking.'),
  (19, 'Catering truck broke down on the apron; replacement meals were loaded late and the Cairo flight left 40 minutes behind schedule.'),
  (20, 'Runway resurfacing at Bahrain reduced arrival capacity; air traffic control holding over the Gulf added 25 minutes to the Cairo sector.'),
  (21, 'A no-show passenger''s checked bag had to be found and removed from the hold for security reasons; 30-minute departure delay to Mumbai.'),
  (22, 'Medical emergency on board when a passenger reported chest pain; diverted to Muscat, handed over to paramedics, then continued to Bahrain 3 hours late.'),
  (23, 'Two cabin crew were stuck in traffic after road flooding in Manama; standby crew were called out and the Dubai departure was delayed 50 minutes.'),
  (24, 'Hydraulic pressure warning during pre-flight checks in Dubai; engineers replaced a pump and the flight departed 2 hours 40 minutes late.'),
  (25, 'Weather radar unserviceable before departure; with thunderstorms forecast over Doha the aircraft could not be dispatched, and swapping to a spare caused an 85-minute delay.'),
  (26, 'Early-morning shuttle from Doha left 2 minutes late on a very light load; quick deplaning on arrival in Bahrain.'),
  (27, 'Auxiliary power unit failed at the gate in 40-degree heat; ground power and air-conditioning carts were used, boarding started late and departure was 55 minutes behind.'),
  (28, 'Severe sandstorm at Riyadh cut visibility below minimums; departure delayed 2 hours 10 minutes and hotel vouchers were issued to connecting passengers in Bahrain.'),
  (29, 'On-time Umrah-season flight to Jeddah; extra Zamzam water allowance and pilgrims travelling in ihram were handled smoothly at check-in.'),
  (30, 'Left Jeddah 8 minutes late after a last-minute gate change; a direct routing from air traffic control still brought the flight into Bahrain on time.'),
  (32, 'Departed Kuwait 3 minutes late; a laptop left on board by a passenger was found by the crew and returned on the next flight.'),
  (33, 'Afternoon Muscat service departed 5 minutes late while waiting for a group connecting from the London flight.'),
  (34, 'Pushed back 10 minutes early with every passenger on board; quiet sector with no service or technical issues reported.'),
  (35, 'Fuel figures were recalculated after a late change in the London weather forecast; extra fuel was uplifted and departure slipped by 40 minutes.'),
  (36, 'Aircraft reached Heathrow late from the outbound Bahrain sector; 50-minute knock-on delay and three passengers missed connections to Mumbai.'),
  (37, 'Cancelled after an engine bleed-air leak was found during the walk-around and no spare long-haul aircraft was available; passengers re-protected on a partner airline via Doha.'),
  (38, 'Industrial action by French air traffic controllers reduced departure slots at Charles de Gaulle; the flight left Paris 50 minutes late.'),
  (39, 'Departed exactly on time; a school group travelling to Istanbul for a robotics competition was seated together at the front of Economy.'),
  (40, 'On-time departure from Istanbul Airport; the cargo hold carried a full shipment of fresh produce and there were no irregularities.'),
  (41, 'Crew duty-time limit was reached after an earlier delay; a standby captain was called in from home and the Cairo departure was 50 minutes late.'),
  (42, 'Air traffic control flow restriction over the Bahrain flight-information region; the Cairo departure slot was pushed back by 60 minutes.'),
  (49, 'Planned: a larger Boeing 787-9 is swapped in for extra capacity ahead of Bahrain National Day holiday travel.'),
  (52, 'Planned: departure retimed by 15 minutes after a new Jeddah slot allocation; passengers informed by email and SMS.'),
  (55, 'Planned: trial of a new Omani-inspired Economy menu on this overnight Muscat rotation.'),
  (60, 'Planned: winter de-icing is expected at Paris; the crew is briefed to allow extra time before departure.'),
  (61, 'Planned: Christmas peak travel and overbooking risk flagged; volunteers who accept rebooking will receive travel vouchers.'),
  (69, 'Planned: very early 04:15 departure; extra check-in counters open from 01:30 for a large tour group.'),
  (75, 'Planned: scheduled engine wash on the aircraft the day before; maintenance confirms it will be ready for the Kuwait flight on time.'),
  (79, 'Planned: a winter storm may hit the UK this week; the flight is being monitored and passengers may be rebooked if Heathrow capacity drops.'),
  (83, 'Planned: a smaller A320neo replaces the usual aircraft because of fleet maintenance; seats in the front rows will be reassigned.'),
  (84, 'Planned: a new boarding area opens at Istanbul Airport; passengers are advised to arrive three hours before departure.'),
  (86, 'Planned: a government delegation travels in Business class; additional security screening at the Cairo gate.'),
  (89, 'Planned: Valentine''s Day promotion with complimentary seat upgrades for couples, subject to availability.'),
  (92, 'Planned: overnight runway maintenance at Doha may cause a longer taxi route and a short delay on departure.'),
  (95, 'Planned: Ramadan timetable in force; this late-evening departure is after iftar and suhoor snack boxes will be served on board.')
) AS n(flight_id, note)
WHERE f.flight_id = n.flight_id;

-- Check: 54 notes, 54 different texts
SELECT count(notes) AS notes, count(DISTINCT notes) AS different_notes
FROM mainline_carrier.flight;