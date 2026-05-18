/* DispensaryIQ — alerts-data.js v1
   Single source of truth for alerts and active triggers.
   Loaded by both index.html (Scorecard BLUF strip) and alerts.html (full view).
   Each item annotated with `states` for state filtering and `trigger_id`
   so a Scorecard click-through can deep-link the matching trigger expansion.
*/

window.DIQ_ALERTS_HIGHLIGHTS = [
  {
    pri:'P0', dim:'COMPETITIVE', states:['NY'], trigger_id:'T-1044',
    title:'FIND under attack in NY — Leal + Rolling Green now 169 doors vs Find 89',
    body:'Leal (69 doors) and Rolling Green (100 doors) combined cover 169 of 558 tracked NY dispensaries. Find is in 89. The two competitor brands jointly outdistribute Find by 1.9x in the NY adult-use market. Q1 at-risk prospect cohort (Leal/RG carried, no Find): 92 dispensaries. Q2 contest zone (all three brands present): 45 dispensaries. Recommend trade-marketing engagement at the 92 Q1 dispensaries before Leal locks in shelf presence. Drill-down: NY watchlist page.',
    cohort:'NY adult-use \u2022 558 tracked dispensaries',
    action:'Trade-marketing follow-up \u2022 92 Q1 prospect dispensaries',
  },
  {
    pri:'P0', dim:'PRICING', states:['NY'], trigger_id:'T-1041',
    title:'Find 3.5g flower NY: 10 of 12 retailers EXTREME above-band',
    body:'Curaleaf-owned anchor $19.50 (3 stores). 10 of 12 tracked retailers in NY are pricing Find 3.5g flower 25%+ above the Curaleaf retail anchor \u2014 average market price $30.00. Margin upside for Curaleaf-owned but brand-equity risk if consumers perceive Find as priced inconsistently with the Curaleaf retail experience. HIGH-confidence anchor.',
    cohort:'NY \u2022 Find 3.5g flower \u2022 12 retailers',
    action:'Review pricing strategy with Curaleaf NY retail leadership',
  },
  {
    pri:'P0', dim:'PRICING', states:['NY'], trigger_id:'T-1042',
    title:'Select 1g vape NY: 7 of 8 retailers EXTREME above-band',
    body:'Curaleaf-owned anchor $35.00 (7 stores). 7 of 8 tracked NY retailers pricing Select 1g vape 25%+ above \u2014 average market $59.65, a 70% premium over Curaleaf-owned. Worst offenders: Good Company NYC ($78, +123%), ZenZest NYC ($68, +94%), RISE Dispensary NY ($60, +71%, n=26). HIGH-confidence anchor.',
    cohort:'NY \u2022 Select 1g vape \u2022 8 retailers',
    action:'Review pricing strategy with retail leadership',
  },
  {
    pri:'P0', dim:'PRICING', states:['NJ'], trigger_id:'T-1043',
    title:'Find 1g pre-roll NJ: 5 of 6 retailers SEVERE below-band',
    body:'Curaleaf-owned anchor $12.00 (4 stores). 5 of 6 tracked NJ retailers pricing 15-25% below \u2014 4 below 15%. Opposite direction from NY: NJ retailers underpricing Find. Brand-wide signal that Find pricing discipline is inconsistent across the pilot footprint. HIGH-confidence anchor.',
    cohort:'NJ \u2022 Find 1g pre-roll \u2022 6 retailers',
    action:'Investigate NJ Find pricing \u2014 promotional or systemic?',
  },
  {
    pri:'P1', dim:'PRICING', states:['IL'], trigger_id:'T-1038',
    title:'Grassroots 1g pre-roll IL: 7 of 7 retailers EXTREME above-band',
    body:'Curaleaf-owned anchor $10.35 (4 stores). All 7 tracked IL retailers pricing 25%+ above. Average market 41% above Curaleaf-retail anchor. Either a value-positioned house brand priced as premium elsewhere, or systematic markup. HIGH-confidence anchor.',
    cohort:'IL \u2022 Grassroots 1g pre-roll \u2022 7 retailers',
    action:'Trade strategy review \u2014 value positioning intent?',
  },
  {
    pri:'P1', dim:'PRICING', states:['NJ'], trigger_id:'T-1031',
    title:'NJ Curaleaf promo penetration 50% \u2014 overheated',
    body:'NJ Curaleaf SKUs discounted at 49.92% rate this week vs NJ market average 31.53%. Could indicate (a) promotional response to competitor push, (b) inventory clearance, or (c) systemic discount strategy. Investigate root cause; the depth of discount in NJ undermines Synthetic-MSRP discipline.',
    cohort:'NJ \u2022 all Curaleaf SKUs \u2022 1,795 observations',
    action:'Promo strategy investigation with NJ trade leadership',
  },
  {
    pri:'P1', dim:'COMPETITIVE', states:['IL'], trigger_id:null,
    title:'Grassroots 3.5g flower IL: TIGHT discipline \u2014 11 of 14 in-band',
    body:'Curaleaf-owned anchor $32.50 (24 stores). Market median $32.00 across 82 observations at 14 retailers. 11 of 14 retailers in-band within +/-5%. The strongest MSRP discipline anywhere in the pilot. Reference case for what good looks like.',
    cohort:'IL \u2022 Grassroots 3.5g flower \u2022 14 retailers',
    action:'Highlight as discipline benchmark in trade reviews',
  },
  {
    pri:'P2', dim:'VISIBILITY', states:['NY'], trigger_id:'T-1019',
    title:'Curaleaf NY shelf score 44.5 \u2014 below pilot average of 47.5',
    body:'Across NY tracked menus, Curaleaf portfolio average shelf position is 44.5 of 100, vs pilot 47.5. Featured share 1.04% \u2014 at category average. Position drag concentrated in Brooklyn and Long Island independents per shelf-quality detail page.',
    cohort:'NY \u2022 all Curaleaf SKUs \u2022 7,606 observations',
    action:'Promotion / merchandising follow-up in NY independents',
  },
];

window.DIQ_ACTIVE_TRIGGERS = [
  {id:'T-1041', pri:'P0', dim:'PRICING',    brand:'Find',      state:'NY', states:['NY'], threshold:'>= +/-25% off, >= 5 retailers',     observed:'10 of 12 above-band',          status:'NEW', age:'0d', assignee:'Brooke + Scott'},
  {id:'T-1042', pri:'P0', dim:'PRICING',    brand:'Select',    state:'NY', states:['NY'], threshold:'>= +/-25% off, >= 5 retailers',     observed:'7 of 8 above-band',            status:'NEW', age:'0d', assignee:'Brooke + Scott'},
  {id:'T-1043', pri:'P0', dim:'PRICING',    brand:'Find',      state:'NJ', states:['NJ'], threshold:'>= +/-15% off, >= 5 retailers',     observed:'5 of 6 below-band',            status:'NEW', age:'0d', assignee:'Brooke + Scott'},
  {id:'T-1044', pri:'P0', dim:'COMPETITIVE',brand:'Find',      state:'NY', states:['NY'], threshold:'Comp doors >= 1.5x brand doors',    observed:'Leal+RG 169 / Find 89 (1.9x)', status:'NEW', age:'0d', assignee:'Brooke + Bobby'},
  {id:'T-1045', pri:'P0', dim:'PRICING',    brand:'Select',    state:'IL', states:['IL'], threshold:'>= +/-25% off, >= 5 retailers',     observed:'6 of 12 above-band (2g vape)', status:'NEW', age:'0d', assignee:'Brooke + Scott'},
  {id:'T-1038', pri:'P1', dim:'PRICING',    brand:'Grassroots',state:'IL', states:['IL'], threshold:'>= +/-25% off, >= 5 retailers',     observed:'7 of 7 above-band (1g pre-roll)', status:'NEW', age:'0d', assignee:'Brooke + Scott'},
  {id:'T-1031', pri:'P1', dim:'PROMOTION',  brand:'Curaleaf',  state:'NJ', states:['NJ'], threshold:'Brand promo > 1.5x market promo',   observed:'49.9% Curaleaf vs 31.5% market', status:'NEW', age:'0d', assignee:'Brooke'},
  {id:'T-1019', pri:'P2', dim:'VISIBILITY', brand:'Curaleaf',  state:'NY', states:['NY'], threshold:'Shelf score < pilot avg - 3',       observed:'44.5 vs pilot 47.5',           status:'NEW', age:'0d', assignee:'Brooke'},
  {id:'T-1015', pri:'P3', dim:'COMPETITIVE',brand:'Curaleaf',  state:'IL', states:['IL'], threshold:'Within 0.5pp of #1 share',          observed:'4.20% vs #1 4.44% (gap 0.24)', status:'NEW', age:'0d', assignee:'Brooke'},
];
