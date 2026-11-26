# Run after jekyll build, from output/: bundle exec ruby ../tests/check_category_archive.rb
require "nokogiri"
require "uri"

site = File.expand_path(ARGV.fetch(0, "_site"))
read_page = ->(file) { Nokogiri::HTML(File.read(file)) }
archive = "/categories/"
homepage = read_page.call(File.join(site, "index.html"))
abort "Missing homepage link to #{archive}" unless homepage.at_css("a[href='#{archive}']")

index = read_page.call(File.join(site, archive, "index.html"))
sections = index.css(".page__content section[id]")
expected = Hash.new { |hash, id| hash[id] = [] }
articles = Dir.glob(File.join(site, "articles/*/index.html"))
abort "No German article pages found" if articles.empty?

articles.each do |file|
  article = read_page.call(file)
  url = file.delete_prefix(site).delete_suffix("index.html")
  level = article.at_css(".article-meta span.level-badge")&.text
  links = article.css("footer .page__taxonomy:has(.fa-folder-open) a[href]")
  abort "Missing category links on #{url}" if links.empty?

  links.each do |link|
    href = URI.parse(link["href"])
    id = URI::DEFAULT_PARSER.unescape(href.fragment.to_s)
    section = sections.find { |node| node["id"] == id }
    unless href.relative? && href.host.nil? && href.path == archive && section && section.at_css("h2")&.text == link.text
      abort "#{url} links to an invalid category: #{href}"
    end
    expected[id] << url
    edition = section.at_css("a[href='#{url}']")
    abort "Missing #{url} in #{id}" unless edition
    abort "Missing #{level} label for #{url}" if level && !edition.text.include?(level)
  end
end

abort "Unexpected or duplicate category sections" unless sections.map { |s| s["id"] }.sort == expected.keys.sort
sections.each do |section|
  urls = section.css("a[href]").map { |link| link["href"] }
  abort "Wrong articles in #{section['id']}" unless urls.sort == expected.fetch(section["id"]).sort
end
puts "Verified #{articles.size} German article pages across #{sections.size} category sections."
