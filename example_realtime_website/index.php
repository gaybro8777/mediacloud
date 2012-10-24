<?php
// initialization
require_once('./lib/CouchSimple.php');
$options = parse_ini_file("config.ini");
$couch = new CouchSimple($options);
?>

<!DOCTYPE html>
<html>
  <head>
    <title>MediaCloud API Client Examples</title>
    <link href="css/mediacloud.css" rel="stylesheet" type="text/css"/>
    <link href="css/bootstrap.min.css" rel="stylesheet" type="text/css"/>
    <script type="text/javascript" src="js/jquery-1.8.2.min.js"></script>
    <script type="text/javascript" src="js/bootstrap.min.js"></script>
    <script type="text/javascript" src="js/d3.v2.min.js"></script>
  </head>

  <body>

<div class="container"> 


  <div class="row">
    <div class="span12">
      <div class="page-header">
        <h1>MediaCloud API Client <small>Examples</small></h1>
      </div>
    </div>
  </div>


<?php
// max story id
$results = json_decode( $couch->send("GET", "/mediacloud/_design/examples/_view/max_story_id") ); 
$maxStoryId = $results->rows[0]->value;

// total story count
$results = json_decode( $couch->send("GET", "/mediacloud/_design/examples/_view/total_stories") ); 
$storyCount = $results->rows[0]->value;

// english story count
$englishStoryCount = null;
$results = json_decode( $couch->send("GET", "/mediacloud/_design/examples/_view/is_english?group=true") ); 
foreach ($results->rows as $row){
  if($row->key==true) {
    $englishStoryCount = $row->value;
  }
}
?>

  <div class="row">
    <div class="span12">
      <p><i>
      <?=$storyCount?> stories in the database (<?=round(100*$englishStoryCount/$storyCount)?>% in english). The max story id is <?=$maxStoryId?>.
      </i></p>
    </div>
  </div>

  <div class="row">

<?php
// story count by length
$wcBarsToShow = 20;
$wcBucketSize = 200;  // must match view
$wcMaxStoryLengthToShow = ($wcBarsToShow)*$wcBucketSize;
$results = json_decode( $couch->send("GET", "/mediacloud/_design/examples/_view/word_counts?group=true&startkey=0&keyend=".$wcMaxStoryLengthToShow) ); 
$wcResults = array();
$wcIncludedStories = 0;
$i = 0;   // prefill array
for($i=0;$i<$wcBarsToShow;$i++){
  $wcResults[$i*$wcBucketSize] = 0;
}
$wcMaxIncludedStoryCount = 0;
foreach ($results->rows as $row){
  if (array_key_exists($row->key,$wcResults)) {
    $wcResults[$row->key] = $row->value;
    $wcMaxIncludedStoryCount = max($wcMaxIncludedStoryCount,$row->value);
    $wcIncludedStories+=$row->value;
  }
}
$wcIncludedStoriesPct = $wcIncludedStories/$storyCount;
?>

    <div class="span6" id="mcStoryLength">
      <h2>Story Length</h2>
      <p>
      Here is a histogram of story length.  The horizontal axis is word length (0-200, 200-400, etc). 
      The vertical axis is the number of stories that have that many words.  This graph includes 
      <?=round($wcIncludedStoriesPct*100)?>% of the stories (excluding the
      <?=$storyCount-$wcIncludedStories?> stories longer than <?=$wcMaxStoryLengthToShow?> words).
      </p>
    </div>


 <?php
// story count by reading level
$rlBarsToShow = 20;
$results = json_decode( $couch->send("GET", "/mediacloud/_design/examples/_view/reading_grade_counts?group=true&startkey=0&endkey=".$rlBarsToShow) ); 
$rlResults = array();
$rlIncludedStories = 0;
$rlMaxIncludedStoryCount = 0;
$rlMaxReadingLevelToShow = 20;
for($i=0;$i<$rlMaxReadingLevelToShow;$i++) {  // prefill array
  $rlResults[$i] = 0;
}
foreach ($results->rows as $row){
  if (array_key_exists($row->key,$rlResults)) {
    $rlResults[$row->key] = $row->value;
    $rlMaxIncludedStoryCount = max($rlMaxIncludedStoryCount,$row->value);
    $rlIncludedStories+=$row->value;
  }
}
$rlIncludedStoriesPct = $rlIncludedStories/$storyCount;
?>

     <div class="span6" id="mcReadability">
      <h2>Story Reading Level</h2>
      <p>
      Here is a histogram of story reading grade level.  The horizontal axis is grade level 
      the story is written at. The vertical axis is the number of stories scored at that grade level. 
      This graph includes <?=round($rlIncludedStoriesPct*100)?>% of the stories (excluding
      <?=$storyCount-$rlIncludedStories?> stories).
      </p>
    </div>
  </div>

  
  <div class="row">
    <div class="span12">
      <h2>Filter For <input type="text" data-provide="typeahead" id="mcPickDomain" placeholder="somenews.com"></h2>
    </div>
    <div id="mcFilteredResults" style="display:none">
      <div class="span6">
        <h3>Word Count</h3>
        <div id="mcFilteredWordCounts"></div>
      </div>
      <div class="span6">
        <h3>Reading Level</h3>
        <div id="mcFilterReadability"></div>
      </div>
    </div>
  </div>


  <div class="row">
    <div class="span12">
      <p><b>Top 10 Sources:</b>
<?php
// sources
function compareRowValue($a,$b){ return $b->value > $a->value; }
$results = json_decode( $couch->send("GET", "/mediacloud/_design/examples/_view/domain_two_part?group=true") ); 
uasort($results->rows,'compareRowValue');
$topTwentyDomains = array_slice($results->rows, 0,10);
foreach($topTwentyDomains as $row){
?>  <a href="http://<?=$row->key?>"><?=$row->key?></a> <span class="badge"><?=$row->value?></span>
<?php
}
?>
      </p>
    </div>
  </div >

</div>

<script type="text/javascript">
function updateFilterResults(domain){
  $('#mcFilteredResults').hide();
  $('#mcFilteredWordCounts').empty();
  $.ajax({
    type: "GET",
    url:"wordcount.js.php?domain="+domain,
    dataType: 'script'
  });
}
$('#mcPickDomain').typeahead({
    source: function (query, process) {
        return $.get('domains.json.php', { query: query }, function (data) {
            return process(data.options);
        });
    },
    updater: function(item){
        updateFilterResults(item);
    }
});
</script>

<script type="text/javascript">
var wcDataset = [
<?php
foreach ($wcResults as $wordCount=>$storyCount){
?> <?=$storyCount?>,
<?php
}
?>
];
var rlDataset = [
<?php
foreach ($rlResults as $wordCount=>$storyCount){
?> <?=$storyCount?>,
<?php
}
?>
];
</script>

<script type="text/javascript">

function histogramChart(container, dataset, chartWidth, chartHeight, barWidth, maxXValue,barsToShow, maxY, xTickCount) {
  var y = d3.scale.linear()
       .domain([0, maxY])
       .range([0, chartHeight]);
  var x = d3.scale.linear()
       .domain([0,maxXValue])
       .range([0, chartWidth]);
  var chart = d3.select(container).append("svg")
       .attr("class", "chart")
       .attr("width", barWidth*barsToShow+50)
       .attr("height", chartHeight+25)
       .append("g")
       .attr("transform", "translate(10,0)");
  chart.selectAll("rect")
       .data(dataset)
       .enter().append("rect")
       .attr("x", function(d,i) { return i*barWidth; })
       .attr("y", function(d) {return chartHeight - y(d);} )
       .attr("height", y)
       .attr("width", barWidth);
  chart.selectAll(".rule")
       .data(x.ticks(xTickCount))
       .enter().append("text")
       .attr("class", "rule")
       .attr("x", x)
       .attr("y", chartHeight)
       .attr("dy", 15)
       .attr("text-anchor", "middle")
       .text(String);
  chart.append("line")
       .attr("x1", 0)
       .attr("x2", chartWidth)
       .attr("y1", chartHeight)
       .attr("y2", chartHeight)
       .style("stroke", "#666");
}

histogramChart("#mcStoryLength",wcDataset,400,100,20,<?=$wcMaxStoryLengthToShow?>,<?=$wcBarsToShow?>, <?=$wcMaxIncludedStoryCount?>,<?=$wcBarsToShow/4?>);

histogramChart("#mcReadability",rlDataset,400,50,20,<?=$rlMaxReadingLevelToShow?>,<?=$rlBarsToShow?>, <?=$rlMaxIncludedStoryCount?>,10);

</script>

  </body>

</html>
